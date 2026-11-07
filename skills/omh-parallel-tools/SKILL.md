---
name: "omh-parallel-tools"
description: "[omh] Parallel tool-call capability in doubt: report the version and whether MCP parallel tool calls are enabled, then apply the diff for parallel tool calls only after approval; an update only on request. Use when the user says: parallel-tools, parallel tools, hermes parallel tools setup, update hermes for parallel tools, check parallel tool support, enable parallel tool calls, verify parallel tools capability, check hermes version for parallel tools."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, hermes-setup]
    category: hermes-setup
    phase: setup
    role: guide
    quality_tier: hermes-setup-gated
---

# Parallel Tools

This is a Hermes-native `parallel-tools` workflow skill.

## Why This Exists

`parallel-tools` exists to give a read-first answer to whether tools run in parallel and to name the one setting a user controls: built-in read-only tools already run concurrently, and an MCP server's tools do only when its `supports_parallel_tool_calls` is true.

## Do Not Use When

- The user wants a general Hermes update unrelated to parallel-tool capability.
- No version or capability question has been asked yet.
- The request needs a repository code change rather than a local version check.

## Examples

Good example:

- Prompt: update hermes for parallel tools — can you check if I'm on a current enough version?
- Expected behavior: Report the installed version and each MCP server's `supports_parallel_tool_calls` value, say that built-in read-only tools already run concurrently, and offer the per-server flag as one diff only for a server whose calls cannot interfere with one another.
- Why: Whether tools run in parallel turns on each MCP server's flag, not on the version, so the version is read and reported and the flag is what is offered.

Bad example:

- Prompt: parallel-tools: update your memory with what we discussed.
- Expected behavior: Route to a memory workflow instead of a parallel-tool capability check.
- Why: Memory update is unrelated to parallel-tool capability or Hermes version.

## Completion Checklist

- If a prerequisite is unmet, mark that item "not applicable" and continue with the rest of the guide instead of blocking or guessing.
- Success is applicable-only: verification passes when every applicable item is confirmed complete, not when every possible item exists.
- The reported capability status matches an observed read, not an assumed default.
- Each proposed `supports_parallel_tool_calls` diff names one server and carries the read/write race caution for that server's tools.
- The diff names the profile whose config holds `mcp_servers.<name>`; the flag applies only to the profile that set it.

## Recovery Notes

- If the installed version cannot be read, report the read failure and continue with the per-server diagnosis; recommend no update on a version you could not read.
- If the update command is unavailable for the user's install path, name the blocker instead of guessing a fix.

## Workflow Lane

- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `live-incident-response`, `automation-blueprint`, `github-event-ops`, `github-issue-intake`, `buzz`, `+40 more`) - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when the user wants to check the parallel-tool capability status, if Hermes tool calls run in parallel, or if the version is current for parallel tool calls, following the shared prerequisite-check, diagnose, guide, diff-approved apply, and verify contract.

    Strong routing signals: `parallel-tools`, `parallel tools`, `hermes parallel tools setup`, `update hermes for parallel tools`, `check parallel tool support`, `enable parallel tool calls`, `verify parallel tools capability`, `check hermes version for parallel tools`, `병렬 도구 설정`, `병렬 툴 확인`, `헤르메스 병렬 도구`, `병렬 도구 쓰려고 헤르메스 업데이트`

## Catalog Metadata

Category: `hermes-setup`
Phase: `setup`
Hermes role: `guide`
Quality tier: `hermes-setup-gated`
Reasoning demand: `light`

Quality bar:

- Prerequisite check: confirm required access; mark unmet prerequisites "not applicable" and skip them.
- Read-only diagnose: inspect non-secret config metadata, `.env` key names and presence only, and version; no secret reads or writes.
- Guide: use Hermes-native secure entry or user-side OAuth/token setup, never chat secrets.
- Diff-approved apply: show the config or `.env` diff with redacted placeholders; apply only after the user explicitly approves.
- Verify: confirm applicable items using non-secret metadata, never secret values.
- This is mostly a verify-only walkthrough: built-in read-only tools already run concurrently with no setting, so prefer reporting capability status over proposing a config change.
- The one change to propose is `mcp_servers.<name>.supports_parallel_tool_calls: true` for a named MCP server, one diff per server, read back from the merged config and active after the user's `/reload-mcp` or a restart; an update, a version, or `agent.parallel_tool_call_guidance` (prompt guidance, on by default) is never presented as the switch that makes tools run in parallel.

Handoff policy:

Run diagnosis and reporting directly in Hermes for parallel-tool capability. Diagnosis reads non-secret metadata only; no writes. Show redacted placeholders in the config or `.env` diff; apply only after the user explicitly approves. Never ask the user to paste secrets into chat. Use Hermes-native secure entry or user-side OAuth/token setup; if unavailable, stop credential application and guide user-side setup. Use only a user-authorized credential store or local configuration; disclose destination and scope first. Keep secrets out of chat, previews, logs and evidence. Do not promise chat or platform non-retention. Delegate to a selected coding executor only if the user needs a change outside a local version/config check.

Required inputs:

- installed Hermes version
- current parallel-tool capability status

Expected outputs:

- read-only diagnosis of the installed version and each MCP server's `supports_parallel_tool_calls` value (absent is false)
- one diff-approved `mcp_servers.<name>.supports_parallel_tool_calls: true` per named MCP server; an update command only when the user asks to update
- a capability status report naming which parallel-tool features are active

Artifact expectations:

- capability status note when the wrapper captures it

Safety rules:

- Do not name a specific version number, release date, or product tier; read and report the installed version instead of assuming one.
- Report the update command for the user to run themselves rather than claiming Hermes restarted or reloaded on its own.
- Propose the flag only for a server whose calls cannot interfere with one another; when two of its calls could touch the same file, record, database, or remote resource, name that race first and leave the choice to the user.

## Runtime Evidence

Preferred harness for this skill: `hermes-setup`.

```sh
omh runtime record --skill parallel-tools --harness hermes-setup --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
