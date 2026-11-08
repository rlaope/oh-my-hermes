---
name: "omh-meta-router"
description: "[omh] Message opens with /omh and a task: meta-routing guidance for a leading /omh command: reason over the imperative task, consult the live workflow catalog, and select or chain the right workflow(s)."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, router]
    category: router
    phase: meta-routing
    role: guide
    quality_tier: routing-gated
    related_skills: [omh-routing]
---

# Meta Router

This is a Hermes-native `meta-router` workflow skill.

## Why This Exists

`meta-router` exists to turn a leading /omh command into a live catalog lookup: it reasons over the imperative task, selects or chains concrete workflows, and keeps the decision inside the observed/prepared evidence boundary instead of guessing from memory.

## Do Not Use When

- The /omh token is not the leading command token.
- The message is a bare picker alias or an OMH catalog/entrypoint question — those belong to `omh-routing`.

## Examples

Good example:

- Prompt: /omh migrate this service off the deprecated API and add tests
- Expected behavior: Consult `omh recommend` on the remainder, then name the recommended chain and start only its first stage; each later engine waits for the user's go-ahead, with explicit observed-vs-prepared evidence boundaries.
- Why: A leading /omh command with an imperative remainder is a meta-routing request that reasons over the live catalog rather than a memorized list.

Bad example:

- Prompt: omh add dark mode
- Expected behavior: Do not meta-route; a bare `omh` alias without a leading slash command is a picker/other-lane signal.
- Why: Meta-routing triggers only on a leading /omh or ./omh command token, not on a bare alias.

## Completion Checklist

- The selected workflow, confidence reason, evidence boundary, and user-facing next action are named.
- Low-confidence or conflicting signals return a picker or clarification instead of forced routing.
- Catalog answers are rendered without shell approval when wrapper metadata is sufficient.

## Recovery Notes

- If bounded recommend queries cannot run through CLI, plugin, or wrapper, retain only the imperative task, mark catalog selection not_observed, and hand back the workflow picker instead of a memorized recommendation.
- If recommendation output contains only `omh-meta-router`, retain the consulted catalog evidence, mark workflow selection unresolved, and hand back the task remainder for a bounded re-query rather than selecting this skill.
- If stage re-queries still leave a multi-stage task low-confidence, retain the consulted catalog evidence, mark the proposed chain tentative, and hand back a clarification question about the unresolved stage.

## Workflow Lane

- Current lane: **Intent -> plan** - clarify, plan, ship, or loop goals.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when the user opens a message with the /omh or ./omh command followed by an imperative task; reason over the task, consult the live OMH catalog, and select or chain the right workflow(s).

    Strong routing signals: `/omh`, `./omh`

## Catalog Metadata

Category: `router`
Phase: `meta-routing`
Hermes role: `guide`
Quality tier: `routing-gated`
Reasoning demand: `light`

Quality bar:

- Route only from a leading `/omh` or `./omh` command token with a task remainder, never from a bare alias.
- Consult the live catalog on every decision instead of a memorized or embedded skill list.
- Exclude `meta-router` from its own recommendation output and choose the next best concrete workflow or chain.
- Report the routing decision as prepared guidance, not execution, review, CI, or merge evidence.

Handoff policy:

Reason over the /omh remainder, select or chain concrete workflows from the live catalog, and prepare a selected executor/runtime handoff only when the chosen chain requires code edits; do not execute code.

Required inputs:

- leading /omh or ./omh command with an imperative remainder
- live OMH catalog via bounded `omh recommend --json` queries
- available shell/CLI or plugin tool surface

Expected outputs:

- selected workflow or chain with rationale
- consulted catalog evidence from the bounded recommend output
- observed-vs-prepared evidence boundary for the routing decision

Artifact expectations:

- runtime run record when a wrapper can observe the meta-routing decision

Safety rules:

- Trigger only on a leading `/omh` or `./omh` command token with a task remainder; bare `/omh`, `./omh`, or `omh` without a slash is a picker/other-lane signal, not meta-routing.
- Shortlist candidates from the installed `skill_view(name='omh-routing', file_path='references/catalog-index.md')` (name plus one-line description per skill) when it is available, then confirm with `omh recommend "<remainder>" --json --limit 3` — the recommend output stays authoritative for the selection and its policy metadata; when the remainder spans multiple stages or the top recommendation is low-confidence, re-query `omh recommend` once per stage with a rephrased stage description instead of dumping the full catalog. Never run `omh docs workflows --json` or `omh list --json` in chat context — their full-catalog output does not fit a chat budget — and never rely on a memorized or embedded skill list; the catalog changes after `omh update`.
- Never select `meta-router` itself from the recommendation output; exclude it and route to the next best concrete workflow or chain.
- Report the selected workflow(s), why, and the observed-vs-prepared evidence boundary; a routing decision is not execution, review, CI, or merge evidence.
- If no shell/CLI surface is available, ask the wrapper to run the bounded `omh recommend` queries or use the plugin tool surface; never guess the catalog from memory — say the catalog is unavailable and offer the workflow picker instead.

## Runtime Evidence

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
