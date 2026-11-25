# Codebase Uml

Load this on-demand contract after the compact `codebase-uml` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user wants the local code index refreshed or a task-scoped handoff pack, not a picture; use `omh-codegraph-refresh`.
- The user wants a narrative first-read tour, reading path, or glossary; use `omh-codebase-onboarding`.
- The user wants a summary card, thumbnail, or explainer image of a PR, meeting, or release rather than a structural diagram; use `omh-image-cards`.
- The user describes a system, cloud, or infrastructure architecture in words and wants it drawn as a styled diagram, with no repository to read the structure from; load Hermes' bundled `architecture-diagram` skill instead of this one.

## Examples

Good example:

- Prompt: Visualize our codebase and drop the picture here so the new teammate can see how the routing package fits.
- Expected behavior: Run `omh codegraph uml --focus src/routing --output .omh/uml/routing.puml`, render with the plan's command, attach the PNG, and read back the legend (units shown, folded, edges pruned).
- Why: The request is a structural picture of one area for a chat surface, which is exactly the bounded diagram this workflow produces.

Bad example:

- Prompt: Just sketch what you think the architecture looks like from the README.
- Expected behavior: Decline to draw from memory; generate the diagram from the tree with `omh codegraph uml` or say the renderer is missing and name the install step.
- Why: A diagram not derived from the actual tree misleads more than no diagram.

## Full Input, Output, and Artifact Expectations

Required inputs:

- repo root or current workspace
- view: whole repo at package level, one area by `--focus <path>`, or module level for a subsystem
- delivery target (chat attachment, PR, doc) which fixes the format: PNG for chat, SVG only when asked
- renderer readiness from the command's render plan (`plantuml` on PATH, or `PLANTUML_JAR` plus `java`)

Expected outputs:

- codebase_uml/v1 model (units, interfaces, edges, omissions) via `omh codegraph uml --json`
- PlantUML source written by `omh codegraph uml --output <file>.puml`
- uml_render_plan/v1 naming the exact render command or the blocker
- one rendered PNG (or SVG on request) attached to the reply, with the omissions legend visible
- not-evidence boundary

Artifact expectations:

- codebase_uml/v1 with `view` (level, depth, focus, caps), `nodes` carrying fan-in-ranked public interfaces, weighted `edges`, `layout` hardening, and `omissions` counts
- uml_render_plan/v1 with `status`, `renderer`, `layout_engine`, `command`, `blockers`, and `notes`
- the rendered image path only after the render command is observed to exit 0 and the file exists
