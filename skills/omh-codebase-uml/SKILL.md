---
name: "omh-codebase-uml"
description: "[omh] Architecture picture of a codebase: turn a repository into one readable, interface-level PlantUML architecture picture - packages or modules, the public symbols other units actually import, bounded import edges - and get it rendered to a single PNG a chat surface can show. Use when the user says: codebase-uml, codebase uml, uml, plantuml, uml diagram, class diagram, package diagram, module diagram."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, planning]
    category: planning
    phase: codebase-uml
    role: planner
    quality_tier: codegraph-gated
    related_skills: [omh-codegraph-refresh, omh-codebase-onboarding, omh-image-cards, architecture-diagram]
---

# Codebase Uml

This is a Hermes-native `codebase-uml` workflow skill.

## Why This Exists

`codebase-uml` exists so 'visualize our codebase' produces one deterministic, readable picture instead of a hand-drawn guess: the interface each unit exposes is ranked by who imports it, the layout is bounded before PlantUML sees it, and every omission the bounding made is printed on the image.

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

## Completion Checklist

- The view (package, focus, or module) matches the question asked, and only one view was rendered unless more were requested.
- The render command and its observed result are recorded before the image is claimed.
- The legend's omissions were read back to the user in the reply.
- Follow-up exploration used narrower generated views, not recollection of the first picture.

## Recovery Notes

- The generator reads Python files only. Before generating, check `omh codegraph summary` finds Python files; for a TypeScript, Go, Java, or Rust repository (or an empty model) say the generator cannot read it, stop, and attach nothing. Do the same when Python is a small share of the source (compare the summary's Python file count with `git ls-files | grep -c -E '\.(ts|tsx|js|go|java|rs)$'`): the picture would show only that part, and saying so is the answer. A picture drawn from a description is a different request, not this workflow.
- If the render plan is blocked, send the PlantUML source path plus the install hint; do not attach a stale or hand-drawn image.
- If the picture is still unreadable, lower `--max-nodes`, narrow `--focus`, or raise `--depth` by one, and say which knob changed.
- If Graphviz `dot` is missing, rerun with `--layout smetana`; the layout differs but the content is identical.

## Workflow Lane

- Current lane: **Intent -> plan** - clarify, plan, ship, or loop goals.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when the user wants to see the shape of a codebase as one picture - a package, module, or focused-area diagram they can drop into Slack, Discord, a PR, or a doc - rather than a prose tour or a refreshed code index.

    Strong routing signals: `codebase-uml`, `codebase uml`, `uml`, `plantuml`, `uml diagram`, `class diagram`, `package diagram`, `module diagram`, `architecture diagram`, `dependency diagram`, `module dependency diagram`, `visualize the codebase`, `visualize this codebase`, `visualize the code`, `visualize the architecture`, `codebase visualization`, `code visualization`, `diagram of the codebase`, `diagram the codebase`, `draw the architecture`, `draw the codebase`, `architecture picture`, `codebase picture`, `picture of the codebase`, `코드베이스 시각화`, `코드베이스 시각화해줘`, `코드베이스를 시각화`, `아키텍처 다이어그램`, `UML 다이어그램`, `패키지 다이어그램`, `클래스 다이어그램`, `코드베이스 다이어그램`, `코드 구조 그림`, `코드베이스 그림으로`, `코드 구조도`, `диаграмма архитектуры`, `нарисуй архитектуру кода`, `схема кодовой базы`, `визуализируй кодовую базу`, `uml диаграмма`, `диаграмма классов`, `архитектурная диаграмма`

## Catalog Metadata

Category: `planning`
Phase: `codebase-uml`
Hermes role: `planner`
Quality tier: `codegraph-gated`
Reasoning demand: `standard`

Quality bar:

- Scope first: whole-repo package view for 'show me the codebase', `--focus <path>` for one area, `--level module` for a subsystem; never render more than one view per request unless asked.
- Generate with `omh codegraph uml --repo <root> --output <dir>/codebase.puml` and read the printed render plan; when it is `blocked`, report the exact blocker and install hint instead of improvising a renderer.
- Render with the plan's command verbatim (`-DPLANTUML_LIMIT_SIZE=8192` stays on) and attach the PNG; use `--layout smetana` when Graphviz `dot` is absent and `--format svg` only when the user asked for SVG.
- Read the legend back to the user in one line: units shown, units folded, edges pruned, symbols hidden - so nobody mistakes 16 boxes for the whole system.
- Answer follow-up exploration by re-running with a narrower `--focus` or `--level module` rather than describing what the first picture omitted from memory.
- Keep the omh theme unless the user asks for `--theme mono`; the theme exists so every OMH diagram reads as one family.
- The picture is a package or module dependency view with ranked public symbols, not a class diagram: say so when the user asked for classes or inheritance.

Handoff policy:

Keep diagram scoping, the `omh codegraph uml` source generation, and the render command in Hermes; the render runs through Hermes' own terminal tool and the image is attached by the chat surface. A generated `.puml` is prepared context; the picture exists only when the render command's exit status and output file are observed, and neither is architecture proof, review, CI, or merge evidence.

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

Safety rules:

- Do not hand-draw the diagram from memory or from a partial read; the boxes and arrows come from `omh codegraph uml` over the actual tree.
- Do not claim the image was rendered or attached without the observed render command result and file.
- Do not present the picture as complete architecture: the legend's folded units, pruned edges, and hidden symbols are part of the answer.
- Never send the diagram to a chat surface or repository the user did not name; the render is local and the attachment is the wrapper's observed action.
- The render surface is the local Java CLI or `PLANTUML_JAR` invocation only; browser/TeaVM PlantUML render options are not part of this workflow.

## Runtime Evidence

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only. Finished work ends with no question and no offer; when a decision only the user can make remains, end with one specific question about that decision, not a list of questions, a generic offer, or a footer; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
