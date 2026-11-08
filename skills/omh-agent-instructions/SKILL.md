---
name: "omh-agent-instructions"
description: "[omh] Agent instruction file for a repo -- AGENTS.md, CLAUDE.md, a Cursor rule: write or update what an agent cannot derive from the code, inside a marked region, with every command verified or marked unverified and no counts that drift. Use when the user says: agent-instructions, agents.md, claude.md, gemini.md, copilot-instructions.md, .cursorrules, cursor rules, cursor rule."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: agent-instructions
    role: planner
    quality_tier: verified-command-and-region-gated
    related_skills: [omh-rules-distill, omh-codebase-onboarding, ulw-context, omh-docs]
---

# Agent Instructions

This is a Hermes-native `agent-instructions` workflow skill.

## Why This Exists

`agent-instructions` exists because the file every handoff target reads first had no owner: `omh-rules-distill` extracts rule candidates, `omh-codebase-onboarding` builds a human reading path, and `ulw-context` aligns terminology, and each reads that file without writing it.

## First Steps

- List every instruction file and which agent reads it before proposing a section.
- Run or ask for the observed run of each command before marking it verified.

## Do Not Use When

- The ask is distilling repeated lessons into reviewed rule candidates; use `omh-rules-distill`.
- The ask is a reading path through the codebase for a new engineer; use `omh-codebase-onboarding`.
- The ask is project terminology alignment -- reviewing the terms this project uses and correcting inconsistent vocabulary; use `ulw-context`.
- The ask is user-facing product documentation; use `omh-docs`.

## Examples

Good example:

- Prompt: update our CLAUDE.md
- Expected behavior: Inventory the instruction files, run or collect each build and test command, mark each verified or unverified, and replace only the marked region with the commands, the generated-file map, the gates, and the costed pitfalls, refusing any count or line number.
- Why: An instruction file that states an unrun command or a stale count sends every later agent the wrong way.

Bad example:

- Prompt: add that the suite has 4,100 tests and the router is at line 212 of chat.py
- Expected behavior: Refuse both values, and write the command that counts the tests and the symbol that locates the router instead.
- Why: Both numbers were already wrong by the next merge.

## Completion Checklist

- Every instruction file and its reader are listed.
- Every command is marked verified with an observed run, or unverified.
- Only the marked region changed, and hand-written text is byte-for-byte.
- No count, line number, or value the code already states was written.
- Every generated file names its source, its regenerate command, and its gate.

## Recovery Notes

- If a command cannot be run here, write it marked unverified with what would verify it.
- If the file has no markers, insert them once around the new section and leave everything else untouched.

## Workflow Lane

- Current lane: **Coding handoff** - coding owners, handoffs, review, CI, and merge evidence.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when the repository's agent instruction file is being written or kept current: AGENTS.md, CLAUDE.md, GEMINI.md, a Cursor rule, or a Copilot instructions file. The output is the build and test commands each marked verified or unverified, the generated-file map with its regenerate command and gate, the byte-exact gates, and the pitfalls that cost time, written inside a marker-delimited region so hand-written sections survive.

    Strong routing signals: `agent-instructions`, `agents.md`, `claude.md`, `gemini.md`, `copilot-instructions.md`, `.cursorrules`, `cursor rules`, `cursor rule`, `agent instruction file`, `agent instructions file`, `instructions file for agents`, `set up agents.md`, `update our claude.md`, `write an agents.md`

## Catalog Metadata

Category: `planning`
Phase: `agent-instructions`
Hermes role: `planner`
Quality tier: `verified-command-and-region-gated`
Reasoning demand: `standard`

Quality bar:

- Inventory every instruction file first and respect closest-file-wins nesting.
- Load `references/instruction-file-method.md` for the section order, the marker convention, the verified and unverified command form, and the drift rules instead of recalling them.
- Record each pitfall with what it cost, so a reader can tell a scar from a preference.
- Pair every generated file with its source, its regenerate command, and the gate that checks it.
- Keep prepared, verified, and written as separate states for every command and section.

Handoff policy:

Keep the section plan, the command verification record, and the region update in Hermes. Every command's outcome is recorded only from executor, operator, or wrapper observed output; the file is written by the executor, and only inside its marked region.

Required inputs:

- which instruction files exist, where they sit, and which agents read them
- the build, test, lint, and regenerate commands the repository uses
- which files are generated, from what source, and which gate checks them
- the pitfalls that have cost time, each with what it cost
- observed output for every command written into the file

Expected outputs:

- instruction_file_inventory/v1
- command_verification_record/v1
- instruction_region_update/v1
- drift_refusal_note/v1 when a requested line would record a count or a line number

Artifact expectations:

- instruction_file_inventory/v1 lists every instruction file, its path, the agents that read it, and which one is closest to each directory, since the closest file wins
- command_verification_record/v1 marks every command verified, with the observed exit status and when, or unverified, and nothing is written as verified without an observed run
- instruction_region_update/v1 replaces only the text between `<!-- omh:agent-instructions:begin -->` and `<!-- omh:agent-instructions:end -->`, and inserts the markers once when absent, so every hand-written section outside them is left byte-for-byte
- drift_refusal_note/v1 names each requested count, line number, or other value the code already states, and writes the command or the file that derives it instead

Safety rules:

- Never write outside the marker-delimited region: the text before `<!-- omh:agent-instructions:begin -->` and after `<!-- omh:agent-instructions:end -->` is hand-written and stays byte-for-byte.
- Never write a command as verified without an observed run; mark it unverified instead.
- Refuse to record counts, line numbers, test totals, or file sizes; they drift, so point at the command or file that derives them.
- Write only what an agent cannot derive from the code; restating the code is drift waiting to happen.
- Never copy secrets, tokens, or private hostnames into an instruction file.

## Runtime Evidence

Preferred harness for this skill: `docs-specialist`.

```sh
omh runtime record --skill agent-instructions --harness docs-specialist --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
