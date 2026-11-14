# Character art-direction record

Write this record before cutting frames and update it on every regeneration.
It travels with the frames and the `qc.json` receipt.

## Identity elements

List what must stay constant in every frame: silhouette, palette (hex values),
proportions (head-to-body ratio), signature props and costume marks. A
regeneration that loses an identity element is rejected even when QC passes.

## Free frames

List each frame that leaves the ground on purpose: frame index, pose, and the
reason (jump apex, fall, lunge). This list is the only source of
`--free-frames`; at most one frame in three, and the verify step compares it with
`free_frames` in `qc.json`. A frame that is merely off the baseline in a bad
generation is not a free frame: regenerate.

## Rejected drafts

For each rejected sheet record the source file hash, the prompt or settings
used, and the reason (scale drift, strip layout, effect packed into a cell,
identity element lost, background not flat). Rejected drafts are evidence, not
waste; do not delete them before the record is written.

## Cell size and baseline

Declare the cell size and the feet baseline the game expects, for example a
512px cell with feet at y=430, and the target frame height passed to the helper.
The helper has no cell-size or baseline argument: it sizes the frame to the
scaled bodies (or to the scaled cell when `--free-frames` is used) and reports
`frame_size` and `baseline_y` in qc.json. Record those, then place the frames on
the game's canvas and baseline in the engine or an import step. The source-row
`anchor_y_max_dev` is the alignment evidence.

## Attack-frame timing

Map each frame index to its game-data timing: startup, active (hit window) and
recovery frames, with the source table or config path. An attack frame that does
not line up with its hit window is a design defect to fix in data or in a new
sheet, not by retiming pixels.

## Real-person or photo sources

A real person's likeness stays recognizable (no SD/chibi redraw unless that
person asks for it). Record the person's consent and the photo's source before
processing, and keep the source photo out of shared evidence.
