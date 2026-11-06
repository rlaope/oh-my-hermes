---
name: "omh-morning-brief"
description: "[omh] Mail and calendar brief configuration: morning brief SETUP (one-time) - connects mail and calendar MCP with read-and-draft-only scope and diff approval; produces the configuration, not the daily brief itself. Use when the user says: morning-brief, morning brief, connect my email for a morning brief, set up morning brief, configure morning brief, connect mail for morning brief, connect calendar for morning brief, set up my morning brief."
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

# Morning Brief

This is a Hermes-native `morning-brief` workflow skill.

## Why This Exists

`morning-brief` exists to connect mail and calendar access for an on-demand brief while limiting the connection to read and create-draft tools and keeping credential entry outside chat, with explicit storage authorization.

## Do Not Use When

- The user wants Hermes to check their email or calendar right now rather than set up the connection.
- The connection is already configured and the user only wants today's brief, not a setup walkthrough; read mail and calendar with the connected tools and summarise them.
- The request needs a repository code change rather than a local MCP config edit.

## Examples

Good example:

- Prompt: connect my email for a morning brief — I want a daily summary of mail and calendar.
- Expected behavior: Check the MCP prerequisite, diagnose the current connection, guide OAuth/token issuance, show the read/draft-only diff, and apply only after approval.
- Why: The request is a mail/calendar integration setup and needs the shared setup contract plus the Send-permission guardrail.

Bad example:

- Prompt: morning-brief: check my email for anything urgent.
- Expected behavior: Route to a mail-reading task instead of starting a connection setup walkthrough.
- Why: A one-off email check is a task request, not an integration setup request.

## Completion Checklist

- If a prerequisite is unmet, mark that item "not applicable" and continue with the rest of the guide instead of blocking or guessing.
- Success is applicable-only: verification passes when every applicable item is confirmed complete, not when every possible item exists.
- The send boundary is confirmed before the brief is reported ready: the server's include list (exact tool names, no globs) where it has an `mcp_servers` entry, otherwise the tools the session registers, hold no send operation (observed), and the report says whether the credential itself can send; else the check stays not_observed.
- With neither mail nor calendar connected the status is blocked, not complete.

## Recovery Notes

- If the mail or calendar prerequisite is unmet, mark that surface "not applicable" and offer the brief scoped to whichever surface is connected.
- If authentication fails, guide reauthorization or reissuance through secure entry or user-side setup; do not request the failed credential in chat or silently retry it.

## Workflow Lane

- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `live-incident-response`, `automation-blueprint`, `github-event-ops`, `github-issue-intake`, `buzz`, `+40 more`) - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when the user wants Hermes to connect mail and calendar access for an on-demand morning brief, following the shared prerequisite-check, diagnose, guide, diff-approved apply, and verify contract.

    Strong routing signals: `morning-brief`, `morning brief`, `connect my email for a morning brief`, `set up morning brief`, `configure morning brief`, `connect mail for morning brief`, `connect calendar for morning brief`, `set up my morning brief`, `모닝 브리핑 설정해줘`, `모닝 브리핑 설정`, `아침 브리핑 설정`, `메일 연동해서 브리핑`

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
- Keep the read/draft-only access boundary — never enable Send permission — as a hard constraint on every apply step, not an optional recommendation; on Gmail that means hiding the send tool, because no drafting scope is free of send.
- When `manage_connections` is in your tool list or tool_search finds it, connect mail and calendar through it rather than a hand-written MCP config diff (`connect` for a hosted account, `install` or `authorize` for a catalog MCP server), and take each app's answer as given: `skipped` means continue with the surface that is connected or ask in chat, never calling it again on your own; when its result does not name the granted access, the send-boundary check stays `not_observed` until the include list or the registered tools are read.

Handoff policy:

Run diagnosis and guidance directly in Hermes for the mail/calendar connection. Diagnosis reads non-secret metadata only; no writes. Show redacted placeholders in the config or `.env` diff; apply only after the user explicitly approves. Never ask the user to paste secrets into chat. Use Hermes-native secure entry or user-side OAuth/token setup; if unavailable, stop credential application and guide user-side setup. Use only a user-authorized credential store or local configuration; disclose destination and scope first. Keep secrets out of chat, previews, logs and evidence. Do not promise chat or platform non-retention. Delegate to a selected coding executor only if the user needs a change outside chat-driven MCP config edits.

Required inputs:

- mail and calendar MCP connection status
- OAuth/app-password availability; value through secure entry or user-side setup only

Expected outputs:

- read-only diagnosis of the current mail/calendar MCP connection state
- diff-approved MCP config write limited to read and create-draft tools

Artifact expectations:

- connection verification note when the wrapper captures it

Safety rules:

- Configure mail and calendar MCP access as read and draft only; never enable Send permission, even if the user asks — drafts stay for the user to send themselves.
- Use Hermes-native secure entry or user-side OAuth/app-password setup, never chat; disclose authorized storage without exposing secrets.
- Do not treat a prepared connection as an observed brief; only report a brief after the connection is verified.
- A draft-capable Gmail credential can also send (every scope that creates drafts sends; `gmail.compose` is "Manage drafts and send emails"); say so before consent. The boundary is the MCP server's `mcp_servers.<name>.tools.include` list with read and create-draft tools only. Report "send tool not exposed, credential can send", never "read and draft-only". Evidence is the include list plus the tools the session registers, not `hermes mcp test`, which lists everything the server offers. Only `gmail.readonly` earns "cannot send", and it has no drafts. Microsoft 365: `Mail.ReadWrite` without `Mail.Send`, `Mail.Send.Shared` or `SMTP.Send`, and it can also delete.
- The bundled `google-workspace` OAuth setup requests `gmail.send` and `gmail.modify` on every run, and its setup script accepts no `--services` flag to narrow the request, though that skill's own instructions show one; Google's consent screen lets the user untick a permission and the script then keeps only what was granted. Never apply that path as this skill's connection, and when the user connects it themselves, report `gmail.send` and `gmail.modify` as granted unless the setup script's `--check` lists them among the missing scopes, never as read-and-draft-only on the strength of the request.

## Runtime Evidence

Preferred harness for this skill: `hermes-setup`.

```sh
omh runtime record --skill morning-brief --harness hermes-setup --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
