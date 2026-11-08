---
name: "omh-sprite-forge"
description: "[omh] Character art to animate in a game: turn image-model sprite sheets into aligned, QC-gated frames with a fail-closed Pillow helper. Use when the user says: sprite-forge, sprite sheet, pixel sprite, pixel art character, game sprite frames, 2d sprite animation, 도트 캐릭터, 스프라이트 시트."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, analysis]
    category: analysis
    phase: sprite-production
    role: operator
    quality_tier: execution-evidence-gated
    related_skills: [omh-show-reel, omh-visual-qa, omh-image-cards]
---

# Sprite Forge

Required: grid sheet from the host image tool on flat #FF00FF, declared rows x cols, cell size and feet baseline, new output directory and execution budget. Output: aligned equal-size frames and sheet, sprite_forge_qc/v1 receipt, character art-direction record.

**HOLD:** Missing inputs or failed contract gates. Prepared OMH routing is not execution or approval.

## Why This Exists

Image models return character poses at drifting scales and offsets, so frames cut by hand jitter in play. This skill couples a grid-sheet contract to a fail-closed processor whose numeric QC decides whether to regenerate the source.

## First Steps

- Read `toolkit/README.md` and `references/execution-and-qa.md` before executing `toolkit/scripts/forge.py`; installation and skill discovery never run it.
- Obtain the raw sheet from the host's own image tool as a grid on flat #FF00FF; OMH generates no images, and a 1xN strip is regenerated as a grid, never processed.
- Record identity elements, rejected drafts, cell size and baseline in `references/character-art-direction.md` form before cutting frames.

Contract: `references/full-contract.md`, loaded before analysis. Procedure: `references/procedure.md`. These are working methods, not an OMH runtime operation.

## Safety Rules

- OMH generates no images: raw sheets come from the host's own image tool, and the helper only processes a supplied file.
- Never hand-patch, redraw or nudge produced frames to pass QC; a REGENERATE verdict sends the work back to a new source sheet.
- A real-person or photo source stays recognizable (no SD/chibi redraw) and requires that person's consent plus a source record before processing.
- Do not auto-install Pillow, import the companion on skill load, open a network connection or overwrite an existing output directory.
- No frame is observed until the helper exits and its files and qc.json are read back; refusal and timeout are not empty-animation findings.

## When to Use

Use when a game character needs animation frames cut from an image-model grid sheet, with measured scale and baseline QC rather than hand-edited frames.

Strong routing signals: `sprite-forge`, `sprite sheet`, `pixel sprite`, `pixel art character`, `game sprite frames`, `2d sprite animation`, `도트 캐릭터`, `스프라이트 시트`, `도트 스프라이트`

## Catalog Metadata

Category: `analysis`
Phase: `sprite-production`
Hermes role: `operator`
Quality tier: `execution-evidence-gated`

## Completion Checklist

- The source sheet is a host-generated grid on #FF00FF with a source record; real-person sources carry consent.
- The actual helper command and exit were observed; frames, sheet and qc.json were read back and hashed, or the blocker is stated.
- free_frames were named before the run, never after a REGENERATE; body_scale_cv and anchor_y_max_dev are quoted from qc.json; a REGENERATE verdict led to a new sheet, not frame edits.

## Recovery Notes

- If the sheet is a 1xN strip or packs a wide effect, ask the host image tool for a grid and a separate effect sheet; do not slice it by hand.
- If Pillow is missing, return the refusal and an explicit optional-environment setup recipe; never synthesize frames.
- If QC returns REGENERATE, regenerate the source with tighter pose and scale instructions and rerun into a new output directory.

## Workflow Lane

- Current lane: **Materials and visual summaries** - web, accessibility, visual QA, files, and packages.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## Runtime Evidence

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; the shared rail's Reply Language And Host Voice and Turn Ending sections hold the full rule.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
