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
python scripts/forge.py process --input sheet.png --rows 2 --cols 3 \
  --output new-frames --key FF00FF --tolerance 30 --target-height 128
```

The helper keeps the largest component per cell plus components >= 5% of it,
applies one common scale (nearest-neighbor) and, by default (`--align feet`),
pins every body's lowest row to one baseline and centres it. For jump, fall,
lunge or weapon-extended frames use `--align cell`: each body keeps the place
its source cell gave it, so a lifted pose stays lifted and the cell is the
pivot; the feet gate is then reported, not applied. An empty cell or a body
touching the cell edge (bleed) is refused with the cell index.

## Read back and decide

Exit codes: 0 PASS, 2 refusal (no outputs), 3 REGENERATE (outputs written as
evidence). On exit 0 or 3, read `qc.json` (`sprite_forge_qc/v1`), every
`frame_NNN.png` and `sheet.png`, and recompute their sha256 against the receipt.

- `body_scale_cv` <= 0.08 and `anchor_y_std` <= 0.05 give PASS. `anchor_y_std`
  is the spread of the feet rows in the SOURCE cells (alignment would hide it
  in the output); it fails a sheet whose figures stand at different heights.
- `body_scale_cv` compares body heights, so poses that differ in height
  (crouch, jump, hit-react) raise it. Gate idle and walk cycles on it; cut other
  moves from their own sheet, or from the same sheet only with the drift named
  in the record.
- `key_spill_share` in qc.json is reported, not gated. A share that is not near
  0 means magenta fringe or a costume colour near the key: regenerate the sheet
  on another flat key (`--key 00FF00`) instead of keying around it.
- REGENERATE means the source drifted: ask the host image tool for a new sheet
  with tighter pose and scale instructions. Never hand-patch, redraw or shift
  produced frames to pass the gate.
- A numeric PASS is technical evidence only; art-direction approval is a
  separate judgement against the character record. Use `omh-visual-qa` when the
  frames must be checked inside a rendered game scene.
