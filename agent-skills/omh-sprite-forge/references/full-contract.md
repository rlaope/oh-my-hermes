# Sprite Forge

Load this on-demand contract after the compact `sprite-forge` body identifies the
workflow. The main body owns routing signals, shared rules, the runtime
operation, delegation fallback, and completion/recovery pointers; this file
holds the workflow-specific detail without copying those shared rails.

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

## When to Use

Routing signals: `sprite-forge`, `sprite sheet`, `pixel sprite`, `pixel art character`, `game sprite frames`, `2d sprite animation`, `도트 캐릭터`, `스프라이트 시트`, `도트 스프라이트`

## Workflow Contract

Category: `analysis`
Phase: `sprite-production`
Hermes role: `operator`
Quality tier: `execution-evidence-gated`
Reasoning demand: `heavy`

Quality bar:

- Require a grid sheet on flat #FF00FF with exact cell division; strips and packed wide effects are regenerated, not cropped.
- Record the real interpreter, Pillow version, command, exit and output hashes; QC numbers come from qc.json, not from inspection by eye.
- Gate on body_scale_cv <= 0.08 and anchor_y_std <= 0.05, and keep technical PASS distinct from art-direction approval.

Handoff policy:

Hermes retains art direction and QC interpretation. Raw sheets come from the host image tool; frames come only from the optional standalone helper within accepted file and execution scope. A prepared command is not observed frame processing.

Required inputs:

- grid sheet from the host image tool on flat #FF00FF
- declared rows x cols, cell size and feet baseline
- new output directory and execution budget

Expected outputs:

- aligned equal-size frames and sheet
- sprite_forge_qc/v1 receipt
- character art-direction record

Artifact expectations:

- Actual `frame_000.png`... equal-size RGBA frames with feet on one shared `baseline_y`, plus the re-composited aligned `sheet.png`.
- Authored `sprite_forge_qc/v1` in `qc.json`: frame count, grid, cell/frame size, per-frame bbox, body_scale_cv, anchor_y_std, thresholds, verdict, hashes and argv.
- A character art-direction record: identity elements, rejected drafts with reasons, cell size + baseline, and attack-frame timing tied to game data.

Detailed procedure steps: `references/procedure.md`.
