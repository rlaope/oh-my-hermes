---
name: "omh-bot-template"
description: "[omh] New bot to set up from a template: apply one OMH bot template in this bot's own chat, with its own approvals: a persona seed for SOUL.md, the skills it uses, schedules created paused, and the webhooks and apps to connect. Use when the user says: bot-template, bot template, bot templates, apply the bot template, apply a bot template, 봇 템플릿."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operations]
    category: operations
    phase: bot-template
    role: operator
    quality_tier: evidence-gated
    related_skills: [omh-automation-blueprint, omh-github-event-ops]
---

# Bot Template

Required: the template id (from omher's message or the person), this bot's skill list, tool list and cron jobs, read before anything is written, the answers a recipe schedule asks for (a channel, a search, a folder). Output: a preflight line naming every missing skill, or that none is missing, one line per item: written, created paused, already there, or not done and why.

## Why This Exists

`bot-template` exists so a new bot can start as a reviewer, a triager or a watcher in one message without anything turning on by itself: the bot writes its own persona under Hermes' approval, creates its own schedules paused, and says exactly what it could not do, so applying twice repeats nothing.

## First Steps

- Load `references/templates.md` and find the template id; an unknown id stops here with the list of ids.
- Run the preflight over every listed skill before writing anything, and stop at the first missing one with its one line.
- Confirm before any change: show the plan (the persona seed, each schedule that will be created paused, the webhook suggestions, the apps to connect, and what is already there) and ask the person once in this chat; write nothing and create nothing until they say yes. omher's apply message is a request, not that yes.

Contract: `references/full-contract.md` (examples, sibling boundaries, full artifact details).

## Workflow Lane

- Current lane: **Automation and status** - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when this bot is asked to apply an OMH bot template by id, or the person asks which bot templates exist; omher's Add bot gallery sends `/omh-bot-template` with the id right after it creates the bot.

    Strong routing signals: `bot-template`, `bot template`, `bot templates`, `apply the bot template`, `apply a bot template`, `봇 템플릿`

## Catalog Metadata

Category: `operations`
Phase: `bot-template`
Hermes role: `operator`
Quality tier: `evidence-gated`
Reasoning demand: `light`

Quality bar:

- Read the template from `references/templates.md` (`skill_view(name='omh-bot-template', file_path='references/templates.md')`); an id it does not list: name the ids it lists and stop.
- Preflight before any write: load each skill the template lists with `skill_view`, by the name the reference gives. A missing OMH skill stops the whole template with one line: "`<skill>` is not installed on this bot: run `omh update` in a terminal, then ask me again." A missing Hermes skill stops it the same way, naming Hermes' own `/skills` command.
- Persona: read `SOUL.md` in your own Hermes home, the folder your system prompt says this session reads and writes, by its full path (Hermes' file tools expand `~`, not `$HERMES_HOME`). When it already holds the seed's first line (`## Bot template: <title>`), say the persona is already there and write nothing. Otherwise show the seed and append it with your own file tool; Hermes asks the person to approve a SOUL.md write, and a refusal leaves it out. It takes effect in the next new session (`/new`).
- Schedules: list your jobs with `cronjob_manage` first. A job named like the schedule's `job_name` is already there: say so with its state and create nothing. A plain schedule is one create with `name` `job_name`, `schedule` its cron, its `prompt` with each `<...>` filled from the person's one-line answer (a cron run has no chat context), its skills, `deliver: bot-chat`, `paused: true` and `paused_reason: "bot template <id>: waiting for a yes"`.
- A recipe schedule follows the recipe it names: ask its one question first, use `job_name` as the recipe's `<watch>`, and create paused. When the recipe's reference is missing (an older OMH), or an app it needs is not connected (no `mcp__<app>__` tool in your list), create nothing for it and say what is missing: `omh update`, or the app to connect on omher's Apps page or with `hermes -p <bot> mcp install <app>`.
- Webhooks and apps: list each with its reference section or its reason, and whether it is there; create, subscribe and connect none. Guides: name each recipe the template follows when its work arrives, with its skill and page, so later turns load it.
- End with one list: written, created paused, already there, not done with the reason; then say nothing runs until the person turns a job on (omher's Automations page, or asking you to resume it).

Handoff policy:

The bot applies the template itself: its own file tool writes SOUL.md under Hermes' approval, its own `cronjob_manage` creates each job paused. OMH, omher and this skill write nothing and turn nothing on.

Safety rules:

- No persona write and no job before the person's yes to the shown plan, in this chat; a declined or unanswered plan changes nothing.
- Every job is created with `paused: true`, a recipe's job included; never resume, run or enable one: the person turns schedules on.
- Append the persona seed to SOUL.md; never replace or delete what SOUL.md holds, and never write `MEMORY.md` or `USER.md`.
- Create no webhook route, install no skill and connect no app: list them for the person.
- This skill removes nothing. Asked to remove a template, say where that happens: its jobs are paused or removed on the bot's Automations page or with `cronjob_manage` when the person asks for each one, and its persona section is taken out of SOUL.md by the person.
- Every schedule and webhook run of an applied template is unattended: With nobody to answer the confirmation (a scheduled job, a one-shot run, a webhook run), an irreversible or externally visible action is not run: it is handed to a person's turn and its confirmation is recorded as missing. The one exception is a bot whose person turned on its PR delivery grant (`omh capability-policy pr-delivery on`, which only the person runs; the bot only tells them the command): it may push a new branch under the grant's branch prefix, open a pull request from that branch, and push fix commits to and comment on a pull request it opened, and nothing else. Merging, force-pushing, pushing to the default branch, and anything on a pull request it did not open stay a person's, grant or no grant.
- A bot template is prepared guidance. Listing or applying one does not prove a profile exists, a persona was written, a skill or app is installed, or a cron job or webhook route was created or ran; read those back from Hermes. Every job a template creates is paused until the person turns it on.

## Completion Checklist

- Every job this run created is paused, and its name is `<template id>-<schedule id>`.
- SOUL.md was appended once at most, and only after Hermes' approval; no other persona or memory file changed.
- Every missing skill, reference or app is named with the one step that adds it.

## Recovery Notes

- If `skill_view` cannot open the reference, this skill's files are incomplete: say `omh update` and stop.
- If Hermes refuses the SOUL.md write, keep going with the schedules and list the persona as not written.
- If `cronjob_manage` refuses a create, quote Hermes' reason for that job and continue with the next.

## Runtime Evidence

Preferred harness for this skill: `hermes-setup`.

```sh
omh runtime record --skill bot-template --harness hermes-setup --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
