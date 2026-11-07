# Sprite-forge execution and QA

Read `toolkit/README.md` for setup, refusals and exact metric definitions. The
backend is **direct Pillow**; numpy is neither used nor required. Skill loading
and resource materialization only read inert text; OMH generates no images.

## Source sheet contract

- The raw sheet comes from the host's own image tool. Ask for a grid (2x2, 2x3,
  ...) on a flat `#FF00FF` background, one pose per cell, the whole body inside
  the cell with margin. A 1xN or Nx1 strip is refused; regenerate it as a grid.
- Wide effects (slashes, muzzle flash, dust) go on a separate sheet, never into
  an oversized character cell.
- The sheet must divide exactly into rows x cols cells. Files over 64 MiB or a
  side over 8192 px are refused before any output is written.
- A sheet with real transparency is used as-is (opaque = alpha >= 128);
  otherwise pixels within `--tolerance` (default 30) of `--key` are background.

## Execute

Use the host's bounded terminal with a finite timeout and a separate,
operator-approved environment that has Pillow. Write into a new output
directory; an existing directory is refused and never overwritten.

```sh
python <skill_dir>/toolkit/scripts/forge.py process --input sheet.png --rows 2 --cols 3 \
  --output new-frames --key FF00FF --tolerance 30 --target-height 128
```

The helper keeps the largest component per cell plus components >= 5% of it,
applies one common scale (nearest-neighbor), pins every body's lowest row to
one baseline and centres it. Frames that leave the ground on purpose (jump,
fall, lunge) are named before the run from the art-direction record with
`--free-frames 2,5`: those keep their offset from the gated frames' pivot and are
excluded from the feet and scale-drift gates (their height must still stay within
30% of the gated median), every other frame stays gated. At most one frame in
three may be freed and at least two stay gated. A pass with freed frames is
`PASS_FREE_FRAMES`, never a bare PASS. The helper cannot see the order of events,
so the rule is structural: the freed frames are the record's list, and a
REGENERATE is never answered by adding frames to it. An empty cell or a body
touching the cell edge (bleed) is refused with the cell index.

## Read back and decide

Exit codes: 0 PASS or PASS_FREE_FRAMES, 2 refusal (no outputs), 3 REGENERATE (outputs written as
evidence). On exit 0 or 3, read `qc.json` (`sprite_forge_qc/v1`), every
`frame_NNN.png` and `sheet.png`, and recompute their sha256 against the receipt.

- `body_scale_cv` <= 0.08 and `anchor_y_max_dev` <= 0.05 give PASS. `anchor_y_max_dev`
  is the largest distance of any gated frame's feet row from the median feet
  row in the SOURCE cells, as a share of the cell height (output alignment
  would hide it, and a standard deviation dilutes one lifted frame). REGENERATE
  on it means a pose stands off the baseline in the source image; the output
  frames themselves are aligned.
- `body_scale_cv` compares body heights over the gated frames, so a crouch or
  hit-react pose raises it. Put such poses on their own sheet, or name them in
  `--free-frames` before the run when the record says they leave the baseline on
  purpose; there is no after-the-fact accepted-drift path.
- `key_spill_share` in qc.json is reported, not gated, and is null on alpha
  input. It has no fixed threshold: compare it with a clean sheet of the same
  character and look at the edge on a dark ground. A fringe or a costume colour
  near the key means regenerate on another flat key (`--key 00FF00`).
- REGENERATE means the source drifted: ask the host image tool for a new sheet
  with tighter pose and scale instructions. Never hand-patch, redraw or shift
  produced frames to pass the gate.
- A numeric PASS is technical evidence only; art-direction approval is a
  separate judgement against the character record. Use `omh-visual-qa` when the
  frames must be checked inside a rendered game scene.
