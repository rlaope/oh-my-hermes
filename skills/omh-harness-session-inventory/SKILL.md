---
name: "omh-harness-session-inventory"
description: "[omh] Lost track of agent sessions and worktrees: normalize Codex, Claude Code, Hermes, OpenCode, Cursor, MCP host, worktree, and wrapper session metadata into one drift-aware inventory. Use when the user says: harness-session-inventory, harness session inventory, session inventory, session adapter, session adapters, harness sessions, mcp inventory, mcp config inventory."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, observability]
    category: observability
    phase: harness-session-inventory
    role: tracker
    quality_tier: workflow-surface-gated
    related_skills: [omh-workspace-audit]
---

# Harness Session Inventory

This is a Hermes-native `harness-session-inventory` workflow skill.

## Why This Exists

`harness-session-inventory` exists so Hermes users can ask for this workflow in chat and get a structured, checkable answer instead of an improvised one.

## Do Not Use When

- The request is already handled by a narrower explicit skill with stronger evidence.
- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.
- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first.
- The request is one repository's own skill, prompt, plugin, or config surfaces and gaps with no cross-harness comparison; use `omh-workspace-audit`.

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
- To recover a previous coding session, list candidates read-only by metadata only (file name, modified time, size): Codex `~/.codex/sessions/`, Claude Code `~/.claude/projects/<project-slug>/`, Hermes `hermes sessions list`; mark an unreadable source not_observed, and read a transcript body only when the person asks for that next step.
- For `omh harness mcp-tool-name-compatibility`, each snapshot is a JSON file with exactly `schema_version` (`mcp_tool_name_compatibility_snapshot/v1`), `target_harness`, `adapter` (an object of `id` and `version`; only `id` `opencode-mcp-tool-naming` with `version` `v1` and `target_harness` `opencode` carries naming rules, and any other adapter reports `unsupported_adapter`), `required_tools` (entries of `logical_name` and `evidence_refs`) and `advertised_tools` (entries of `name`, `observation` of `registered` or `config_only`, and `evidence_refs`); one `--snapshot` per distinct target harness (1 to 20 files), and a malformed file is refused with no field named.
- Write each of the other inventory artifacts as a table with columns entry, source path, and state in {observed, prepared, missing, stale, drifted, not_observed}, so completion can be checked row by row.

## Workflow Lane

- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `live-incident-response`, `automation-blueprint`, `github-event-ops`, `github-issue-intake`, `buzz`, `+40 more`) - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when operators need a cross-harness/session/MCP/worktree inventory and drift summary before claiming any host loaded, connector ran, or agent session progressed.

    Strong routing signals: `harness-session-inventory`, `harness session inventory`, `session inventory`, `session adapter`, `session adapters`, `harness sessions`, `mcp inventory`, `mcp config inventory`, `mcp drift`, `harness drift`, `connector drift`, `worktree inventory`, `worktree lifecycle`, `operator inventory`, `control pane inventory`, `codex session inventory`, `claude code session inventory`, `find previous coding session`, `recover coding session`, `previous codex coding session`, `coding session recall`, `세션 인벤토리`, `지난 코딩 세션`, `코딩 세션 복구`, `세션 기억 복구`, `하네스 세션`, `하네스 드리프트`, `MCP 인벤토리`, `MCP 설정 드리프트`, `워크트리 인벤토리`, `커넥터 드리프트`, `сессии агентов`, `инвентарь харнессов`, `восстанови сессию агента`, `инвентарь сессий`, `каждый харнесс`, `харнесс подхватывает`, `харнес подхватывает`

## Catalog Metadata

Category: `observability`
Phase: `harness-session-inventory`
Hermes role: `tracker`
Quality tier: `workflow-surface-gated`
Reasoning demand: `standard`

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

Preferred harness for this skill: `harness-session-inventory`.

```sh
omh runtime record --skill harness-session-inventory --harness harness-session-inventory --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
