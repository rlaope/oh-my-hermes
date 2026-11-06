---
name: "omh-sprite-forge"
description: "[omh] Character art to animate in a game: turn image-model sprite sheets into aligned, QC-gated frames with a fail-closed Pillow helper. Use when the user says: sprite-forge, sprite sheet, pixel sprite, pixel art character, game sprite frames, 2d sprite animation, 도트 캐릭터, 스프라이트 시트."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, analysis]
    category: analysis
    phase: sprite-production
    role: operator
    quality_tier: execution-evidence-gated
---

# Sprite Forge

This is an OMH `sprite-forge` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

Image models return character poses at drifting scales and offsets, so frames cut by hand jitter in play. This skill couples a grid-sheet contract to a fail-closed processor whose numeric QC decides whether to regenerate the source.

## First Steps

- Read `toolkit/README.md` and `references/execution-and-qa.md` before executing `toolkit/scripts/forge.py`; installation and skill discovery never run it.
- Obtain the raw sheet from the host's own image tool as a grid on flat #FF00FF; OMH generates no images, and a 1xN strip is regenerated as a grid, never processed.
- Record identity elements, rejected drafts, cell size and baseline in `references/character-art-direction.md` form before cutting frames.

## Do Not Use When

- Create a product showcase video for a launch, with narration and subtitles; use `omh-show-reel`.
- The task is judging already-rendered UI screenshots or layout captures; use `omh-visual-qa`.
- The output is an image card or visual prompt card summarizing source material; use `omh-image-cards`.

## Examples

Good example:

- Prompt: Make a pixel sprite sheet for my game character.
- Expected behavior: Get a 2x3 #FF00FF grid from the host image tool, record art direction, run the helper, then read back frames and qc.json and regenerate on a REGENERATE verdict.
- Why: Animation frames need measured scale and baseline consistency, not a single illustration.

Bad example:

- Prompt: Tighten the CSS pixel spacing on this sheet of settings cards.
- Expected behavior: Answer as a front-end styling question; do not run a sprite processor.
- Why: Pixel and sheet vocabulary alone does not establish game-character frames.

## Completion Checklist

- The source sheet is a host-generated grid on #FF00FF with a source record; real-person sources carry consent.
- The actual helper command and exit were observed; frames, sheet and qc.json were read back and hashed, or the blocker is stated.
- body_scale_cv and anchor_y_std are quoted from qc.json; a REGENERATE verdict led to a new sheet, not frame edits.

## Recovery Notes

- If the sheet is a 1xN strip or packs a wide effect, ask the host image tool for a grid and a separate effect sheet; do not slice it by hand.
- If Pillow is missing, return the refusal and an explicit optional-environment setup recipe; never synthesize frames.
- If QC returns REGENERATE, regenerate the source with tighter pose and scale instructions and rerun into a new output directory.



## When to Use

Use when a game character needs animation frames cut from an image-model grid sheet, with measured scale and baseline QC rather than hand-edited frames.

    Strong routing signals: `sprite-forge`, `sprite sheet`, `pixel sprite`, `pixel art character`, `game sprite frames`, `2d sprite animation`, `도트 캐릭터`, `스프라이트 시트`, `도트 스프라이트`

## Catalog Metadata

Category: `analysis`
Phase: `sprite-production`
Quality tier: `execution-evidence-gated`
Reasoning demand: `heavy`

Quality bar:

- Require a grid sheet on flat #FF00FF with exact cell division; strips and packed wide effects are regenerated, not cropped.
- Record the real interpreter, Pillow version, command, exit and output hashes; QC numbers come from qc.json, not from inspection by eye.
- Gate on body_scale_cv <= 0.08 and anchor_y_std <= 0.05, and keep technical PASS distinct from art-direction approval.

Required inputs:

- grid sheet from the host image tool on flat #FF00FF
- declared rows x cols, cell size and feet baseline
- new output directory and execution budget

Expert clarification questions:
- `grid sheet from the host image tool on flat #FF00FF`
  - English: Which host image tool produces the sheet, which grid (2x2, 2x3, ...) holds which pose, and is the background flat #FF00FF?
  - Korean: Which host image tool produces the sheet, which grid (2x2, 2x3, ...) holds which pose, and is the background flat #FF00FF?

Expected outputs:

- aligned equal-size frames and sheet
- sprite_forge_qc/v1 receipt
- character art-direction record

Artifact expectations:

- Actual `frame_000.png`... equal-size RGBA frames with feet on one shared `baseline_y`, plus the re-composited aligned `sheet.png`.
- Authored `sprite_forge_qc/v1` in `qc.json`: frame count, grid, cell/frame size, per-frame bbox, body_scale_cv, anchor_y_std, thresholds, verdict, hashes and argv.
- A character art-direction record: identity elements, rejected drafts with reasons, cell size + baseline, and attack-frame timing tied to game data.

Safety rules:

- OMH generates no images: raw sheets come from the host's own image tool, and the helper only processes a supplied file.
- Never hand-patch, redraw or nudge produced frames to pass QC; a REGENERATE verdict sends the work back to a new source sheet.
- A real-person or photo source stays recognizable (no SD/chibi redraw) and requires that person's consent plus a source record before processing.
- Do not auto-install Pillow, import the companion on skill load, open a network connection or overwrite an existing output directory.
- No frame is observed until the helper exits and its files and qc.json are read back; refusal and timeout are not empty-animation findings.

Procedure: load `references/procedure.md`.

## Runtime Evidence

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Record actual tool results, or
`not_observed` / `not_available`, in the record; never invent dispatch or host
accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Reply in the user's own words and the host's own voice: the host's persona owns
reply language, tone, speech level, and sentence endings, progress updates
included (where it sets no language, use the one the user wrote in), and OMH
shapes structure and content only; OMH's record terms
(surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in
records and tool calls, never in the sentence the user reads unless they ask
about one; and when a real unresolved user decision or a useful briefing discussion
remains, offer one specific, content-linked question. Completed work needs no question;
omit unrelated non-action footers and generic offers to continue.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
