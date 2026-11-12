---
name: "omh-toolbelt-readiness"
description: "[omh] Which tools and credentials a workflow needs: inventory which MCP servers, CLIs, APIs, credentials, and connectors a workflow needs; use `omh-external-connector-readiness` to assess one named integration. Use when the user says: toolbelt-readiness, mcp readiness, tool readiness, plugin readiness, connector readiness, needed mcp, api credential, missing cli."
disable-model-invocation: true
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, tools]
    category: tools
    phase: readiness-check
    role: tracker
    quality_tier: workflow-surface-gated
---

# Toolbelt Readiness

This is an OMH `toolbelt-readiness` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

`toolbelt-readiness` exists so the tools, CLIs, credentials, and connectors a workflow needs are listed as present, missing, optional, or unsafe before the work starts, instead of failing midway on a tool nobody checked.

## Do Not Use When

- One named integration needs assessing end to end before adoption; use `omh-external-connector-readiness`.
- The question is which coding owner should run the work.
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



## When to Use

Use when a workflow depends on MCP, CLI, API credentials, or connectors and Hermes must show installed, missing, optional, and unsafe tools.

    Strong routing signals: `toolbelt-readiness`, `mcp readiness`, `tool readiness`, `plugin readiness`, `connector readiness`, `needed mcp`, `api credential`, `missing cli`, `missing plugin`, `missing connector`, `external connector`, `external tool`, `mcp server`, `mcp servers`, `mcp tool`, `mcp tools`, `toolbelt`, `github cli`, `linear cli`, `jira cli`, `notion connector`, `google drive connector`, `gmail connector`, `slack api`, `browser tool`, `image generator connector`, `mcp`, `credential`, `외부 도구`, `외부 연결`, `커넥터`, `플러그인`, `자격증명`

## Catalog Metadata

Category: `tools`
Phase: `readiness-check`
Quality tier: `workflow-surface-gated`
Reasoning demand: `standard`

Quality bar:

- Name the user-facing workflow objective, required context, next action, and stop condition.
- Separate prepared guidance from observed platform, runtime, connector, file, memory, or delivery evidence.
- Expose missing tools, credentials, targets, or observations as user-visible gaps.
- On Hermes, count a native tool as present when it is in your tool list or tool_search finds it: a tool deferred behind tool_search is reached through `tool_call` and is never listed as missing, and a Hermes version number never decides presence. Present is not authorized or working.

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
