# Bot Template

Load this on-demand contract after the compact `bot-template` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The person wants one recurring job of their own design, with no bot template behind it; use `omh-automation-blueprint`.
- The person wants to wait on one pull request's checks now; use `omh-github-event-ops` and its PR watch.

## Examples

Good example:

- Prompt: /omh-bot-template Apply the bot template `pr-review` to this bot.
- Expected behavior: Load the template, check each listed skill, show the plan and wait for a yes, then append the persona after Hermes' approval, create `pr-review-review-queue` paused, list the two webhook suggestions, and end with the done/not-done list.
- Why: The id is in the catalog and every write goes through the bot's own tools and approvals.

Bad example:

- Prompt: Apply the inbox-triage bot template and turn the digest on so it runs tomorrow.
- Expected behavior: Show the plan and, after the person's yes, apply it with every job paused; then say turning the digest on is the person's: resume it on the Automations page or ask me to resume `inbox-triage-morning-digest` as its own request.
- Why: Applying a template never turns a schedule on; resuming is a separate yes from the person.

## Full Input, Output, and Artifact Expectations

Required inputs:

- the template id (from omher's message or the person)
- this bot's skill list, tool list and cron jobs, read before anything is written
- the answers a recipe schedule asks for (a channel, a search, a folder)

Expected outputs:

- a preflight line naming every missing skill, or that none is missing
- one line per item: written, created paused, already there, or not done and why

Artifact expectations:

- SOUL.md gains the template's persona section once, through the bot's own file tool and Hermes' approval
- each schedule is one paused Hermes cron job named `<template id>-<schedule id>`
