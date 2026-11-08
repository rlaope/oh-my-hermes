---
name: "omh-skill"
description: "[omh] Installing, removing, or editing skills: managing local skills. Use when the user says: skill, skills, manage skills."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, operator]
    category: operator
    phase: skill-management
    role: tracker
    quality_tier: evidence-gated
    related_skills: [omh-capability-toggle, omh-skill-scout, omh-skill-health, hermes-agent-skill-authoring]
---

# Skill

This is a Hermes-native `skill` workflow skill.

## Why This Exists

`skill` exists to route listing, reading, searching, installing, and editing skills to Hermes' own skill tools and commands, and to keep OMH-managed skills, whose bodies OMH generates, out of hand edits.

## Do Not Use When

- The user wants an OMH capability family turned on or off; use `omh-capability-toggle`.
- The user wants a public skill found and vetted before installing it; use `omh-skill-scout`.
- The user wants skill health checked: stale surfaces, failure patterns, or pending amendments; use `omh-skill-health`.
- The user is writing or editing a skill that ships in the hermes-agent repository itself rather than a local one; load Hermes' `hermes-agent-skill-authoring` skill instead of this one (if skill_view cannot find it: hermes skills install official/software-development/hermes-agent-skill-authoring).

## Examples

Good example:

- Prompt: which skills do I have, and add one for our release checklist
- Expected behavior: List with `skills_list`, read close matches with `skill_view`, create the new skill with `skill_manage` under a name of the person's own, and report it from the tool result.
- Why: Listing and creating a person's own skill are Hermes' native skill tools' job.

Bad example:

- Prompt: skill: patch omh-plan's SKILL.md with skill_manage so it asks fewer questions
- Expected behavior: Decline the in-place edit and offer a separately named skill or an OMH catalog change instead.
- Why: An OMH-managed body is generated from OMH's catalog, so the patch would not carry into the next generation.

## Completion Checklist

- Every listed or read skill came from `skills_list` or `skill_view`, not a guessed path.
- Each create, edit, or delete is reported from `skill_manage`'s result, and no OMH-managed skill was edited.
- Search, install, uninstall, and hiding are named as the person's own `hermes skills` commands.

## Recovery Notes

- If `skill_manage` is absent from this session, give the person the exact change instead of writing the skill through another tool.
- If the person wants an OMH-managed skill changed, offer a separately named companion skill or an OMH catalog change, never an in-place edit.

## Workflow Lane

- Current lane: **Automation and status** - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use for local skill listing, search, add, remove, or edit tasks.

    Strong routing signals: `skill`, `$skill`, `skills`, `manage skills`

## Catalog Metadata

Category: `operator`
Phase: `skill-management`
Hermes role: `tracker`
Quality tier: `evidence-gated`
Reasoning demand: `light`

Quality bar:

- Read skills with Hermes' own tools: `skills_list` to list them and `skill_view` to read a skill or one of its files.
- Create, edit, or delete a skill of the person's own with `skill_manage` when `skill_manage` is in your tool list or tool_search finds it; otherwise hand the person the exact change.
- Registry search, install, removal of a hub-installed skill, and per-platform hiding are the person's own `hermes skills search`, `install`, `uninstall`, and `config` in a terminal, with `/skills search` and `/skills install` in a CLI or TUI session; after an install, `/reload-skills` in a running session makes the new skill available as `/<name>` without a restart.
- Never edit or delete an OMH-managed skill with `skill_manage`: OMH generates its body from its catalog, so the change does not carry into the next generation; put the lesson in a separately named skill instead. An OMH-managed skill is one OMH installed, under a label OMH's catalog renders such as `omh-plan` or `ulw-work`; a companion skill the person or an agent created is theirs, whatever its name.

Handoff policy:

Use Hermes for inventory and guidance; delegate only repository code changes to the selected coding executor.

Required inputs:

- skill action
- target skill name or directory

Expected outputs:

- skill inventory or mutation result
- verification note

Artifact expectations:

- manifest update when managed skills change

Safety rules:

- Write no Hermes config: hiding, enabling, or installing a skill is the person's own command.
- Report a skill changed only from `skill_manage`'s result or a re-read with `skill_view`.

## Runtime Evidence

Preferred harness for this skill: `docs-specialist`.

```sh
omh runtime record --skill skill --harness docs-specialist --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. When the requested output is delivered, put any open points inside the result and end with no question or offer; only when the person asked to choose or decide and that choice is still theirs, end with one specific question about it, not a list, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
