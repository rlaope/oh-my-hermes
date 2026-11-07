---
name: "omh-toolbelt-readiness"
description: "[omh] Which tools and credentials a workflow needs: inventory which MCP servers, CLIs, APIs, credentials, and connectors a workflow needs; use `omh-external-connector-readiness` to assess one named integration and `omh-executor-runtime-readiness` to choose the coding owner. Use when the user says: toolbelt-readiness, mcp readiness, tool readiness, plugin readiness, connector readiness, needed mcp, api credential, missing cli."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, tools]
    category: tools
    phase: readiness-check
    role: tracker
    quality_tier: workflow-surface-gated
    related_skills: [omh-external-connector-readiness, omh-executor-runtime-readiness]
---

# Toolbelt Readiness

This is a Hermes-native `toolbelt-readiness` workflow skill.

## Why This Exists

`toolbelt-readiness` exists so the tools, CLIs, credentials, and connectors a workflow needs are listed as present, missing, optional, or unsafe before the work starts, instead of failing midway on a tool nobody checked.

## Do Not Use When

- One named integration needs assessing end to end before adoption; use `omh-external-connector-readiness`.
- The question is which coding owner should run the work; use `omh-executor-runtime-readiness`.
- The user wants a tool installed, a credential validated, or a connector called now; the card names that step and who runs it, and performs none of them.

## Examples

Good example:

- Prompt: toolbelt-readiness what MCP or CLI tools do I need for weekly Linear and GitHub triage?
- Expected behavior: Produce `prepare_toolbelt_readiness` with required context, wrapper actions, and not-evidence boundaries.
- Why: Linear and GitHub triage needs two read credentials and matching MCP servers or CLIs, listed before the first run.

Bad example:

- Prompt: toolbelt-readiness claim Gmail access works without an observed credential check.
- Expected behavior: Report the missing observed evidence or authority instead of claiming the external step happened.
- Why: Prepared OMH guidance is not platform, runtime, connector, file, memory, or delivery evidence.

## Completion Checklist

- Each required tool is listed once as present, missing, optional, or unsafe, with how it was observed: the tool list or `tool_search` for native tools, `hermes mcp list` on Hermes (else the host's MCP list) for MCP servers, `command -v <cli>` for CLIs, the env-var NAME only for credentials.
- Unsafe says why: a tool that writes outside the stated scope, or a credential broader than the task needs.
- Name the smallest next verification or handoff and who runs it, instead of claiming completion from narration.

## Recovery Notes

- If tool_search finds a deferred native tool but access is untested, retain its present classification, mark API access not_observed, and hand back the tool_call step for a user-approved check instead of listing the tool as missing.
- If a required MCP server or CLI is absent, retain the present, optional, and unsafe inventory entries, mark workflow readiness unresolved, and hand back the missing dependency and installation owner without installing it.

## Workflow Lane

- Current lane: **Automation and status** - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when a workflow depends on MCP, CLI, API credentials, or connectors and Hermes must show installed, missing, optional, and unsafe tools.

    Strong routing signals: `toolbelt-readiness`, `mcp readiness`, `tool readiness`, `plugin readiness`, `connector readiness`, `needed mcp`, `api credential`, `missing cli`, `missing plugin`, `missing connector`, `external connector`, `external tool`, `mcp server`, `mcp servers`, `mcp tool`, `mcp tools`, `toolbelt`, `github cli`, `linear cli`, `jira cli`, `notion connector`, `google drive connector`, `gmail connector`, `slack api`, `browser tool`, `image generator connector`, `mcp`, `credential`, `외부 도구`, `외부 연결`, `커넥터`, `플러그인`, `자격증명`

## Catalog Metadata

Category: `tools`
Phase: `readiness-check`
Hermes role: `tracker`
Quality tier: `workflow-surface-gated`
Reasoning demand: `standard`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.
- On Hermes, count a native tool as present when it is in your tool list or tool_search finds it: a tool deferred behind tool_search is reached through `tool_call` and is never listed as missing, and a Hermes version number never decides presence. Present is not authorized or working.

Handoff policy:

Keep this as Hermes-facing orchestration guidance first. Prepare executor, connector, gateway, or host-runtime handoff only when the user accepts that next step and observed evidence can be recorded.

Required inputs:

- user request
- target context
- delivery or status expectation
- known missing evidence

Expected outputs:

- toolbelt-readiness/v1 card or guidance
- next action
- prepared-vs-observed boundary

Artifact expectations:

- toolbelt-readiness/v1 metadata-only runtime or wrapper card when recorded

Safety rules:

- A toolbelt readiness card is not MCP server installation, credential validation, API access, connector invocation, or successful workflow execution evidence.
- Do not claim connector, gateway, runtime, file generation, memory mutation, or host automation evidence from prepared guidance.

## Runtime Evidence

Preferred harness for this skill: `toolbelt-readiness`.

```sh
omh runtime record --skill toolbelt-readiness --harness toolbelt-readiness --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
