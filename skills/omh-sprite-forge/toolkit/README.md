# Optional sprite-forge toolkit

Original OMH helpers and synthetic fixtures, MIT, copyright 2026 oh-my-hermes
contributors. No upstream sprite-forge code is copied. The implemented backend
is **direct Pillow**; numpy is neither used nor required. Loading/installing
the skill reads text only and does not install packages or execute a helper.

## Operator setup and command

Requires Python 3.11+ and optional `pillow` in a separate operator-owned
environment. Explicit setup example (not auto-run by OMH):

```sh
uv venv --python 3.12 /your/scratch/sprite-venv
uv pip install --python /your/scratch/sprite-venv/bin/python pillow
```

Run from this toolkit's directory using that interpreter and a finite host
terminal timeout:

```sh
/your/scratch/sprite-venv/bin/python scripts/forge.py process \
  --input sheet.png --rows 2 --cols 3 --output /your/scratch/new-frames \
  --key FF00FF --tolerance 30 --target-height 128
```

`--help` needs only stdlib and works without Pillow. When Pillow is missing,
`process` and `selftest` exit nonzero and create no output directory.
`examples/layout.json` is a small text example of the layout/arguments (not an
executable fixture).

## Inputs and refusals

- Input is a single PNG sheet laid out as a grid (2x2, 2x3, ...). Strip
  layouts (1 row or 1 column with more than one cell) are refused with a
  message telling the operator to regenerate as a grid. Wide effects
  (slashes, muzzle flashes) belong on a separate sheet, not an oversized cell.
- The sheet must divide exactly into rows x cols equal cells.
- Refused before any output is written (exit 2, message on stderr):
  missing Pillow; file larger than **64 MiB** (`MAX_FILE_BYTES`); a side
  larger than **8192 px** (`MAX_SIDE_PX`) — both module constants so tests
  can lower them; an existing output directory (no overwrite flag exists);
  traversal or symlink path components (only macOS's own `/etc`, `/tmp`,
  `/var` into `/private` are trusted); an empty cell; a cell whose opaque
  region touches the cell edge (bleed) — the message names the cell index.
- Background rule: if the sheet has an alpha channel with any transparency,
  that alpha is used as-is (opaque = alpha >= 128) and no key color is
  guessed. Otherwise the sheet is chroma-keyed: a pixel is background when
  each RGB channel is within `--tolerance` (default 30) of `--key`
  (default `FF00FF`).
- Per cell the largest 4-connected opaque component is kept, plus any
  component with pixel area at least 5% of that largest component
  (`SMALL_COMPONENT_FRACTION`); smaller specks are dropped. No de-fringing,
  halo removal or geometry repair is performed.
- The caps are input refusals, not a performance guarantee: connected-component
  analysis is pure Python and is intended for ordinary sprite sheets, not for
  8192x8192 stress loads. These do not replace the host execution timeout.
- No network access; nothing outside the new output directory is written.

## Outputs and exact metric definitions

- `frame_000.png`, `frame_001.png`, ...: equal-size RGBA frames, every body's
  bottom (feet) on one shared baseline row (`baseline_y`, the frame's last
  row), each body horizontally centered; frames named in `--free-frames` keep
  their offset from the gated frames' pivot (median centre x and feet row).
- `sheet.png`: the frames re-composited into an aligned rows x cols grid.
- `qc.json` (`sprite_forge_qc/v1`): the numeric QC receipt. Its own hash is
  excluded; hash it separately when retaining evidence.

Exact metric definitions:

- **body height** (per frame): number of pixel rows spanned by the opaque
  bounding box of the retained components in that cell, measured on the input
  sheet before any scaling.
- **body_scale_cv**: population standard deviation of the per-frame body
  heights divided by their mean, measured before common scaling.
  Threshold: **0.08**.
- **common scale**: a single scale factor applied to all frames so the median
  body height maps to `--target-height`; omitted `--target-height` keeps the
  median, i.e. scale = 1.0. Resizing is nearest-neighbor.
- **baseline_y**: without `--free-frames` the shared bottom row every body's
  feet sit on (the frame's last row), bodies horizontally centered. With it,
  frames use the scaled cell as canvas and `baseline_y` is the median source
  feet row after scaling.
- **free_frames / gated_frames**: `--free-frames 2,5` (0-based) names frames that
  leave the ground on purpose. They keep their offset from the gated pivot and
  are excluded from the feet and scale-drift gates, though their height must stay
  within 30% of the gated median (`free_height_ratio_dev`). At most one frame in
  three may be freed and at least two stay gated. A pass with freed frames is
  `PASS_FREE_FRAMES` (exit 0), printed with `free_frames` and `gated_frames`. Name
  the frames from the art-direction record before the run; the helper cannot see
  the order of events, so the list in the record is the control.
- **anchor_y_max_dev**: largest distance of a gated frame's feet row (lowest
  retained opaque row) from the median feet row, measured on the INPUT sheet and
  divided by the cell height. It is measured before alignment because alignment
  sets the output feet by construction, and as a maximum because a standard
  deviation dilutes one lifted frame among many. Threshold: **0.05**.
  REGENERATE on it means a pose stands off the baseline in the source image; the
  output frames are aligned. `anchor_y_std` (population std) is reported only.
- **key_spill_pixels / key_spill_share**: retained opaque pixels within twice
  `--tolerance` of the key colour (magenta fringe, or a costume colour near the
  key). Reported, not gated, null on alpha input, and without a fixed threshold:
  compare with a clean sheet and look at the edge on a dark ground; a fringe
  means regenerate on another key (`--key 00FF00`) or despill outside this helper.
- **verdict**: `PASS` when `body_scale_cv <= 0.08` and `anchor_y_max_dev <= 0.05` over the gated frames,
  otherwise `REGENERATE`. A REGENERATE verdict still writes all outputs but
  exits with code 3; fix the source sheet, not the produced frames.

`qc.json` also records frame_count, rows, cols, cell_size, frame_size,
baseline_y, per-frame bbox/height, thresholds, input sha256, output sha256s
(frames and sheet), script sha256, Pillow version and argv.

Exit codes: **0** PASS; **2** refusal (no output directory or files);
**3** REGENERATE (outputs written for evidence). Read the files back and
verify actual bytes and QC values, not just the success message.

## Self test

```sh
/your/scratch/sprite-venv/bin/python scripts/forge.py selftest \
  --output /your/scratch/sf-selftest-new
```

Synthesizes a 2x2 #FF00FF sheet in memory with four simple figures of slightly
varied height/offset, processes it, asserts 4 frames of equal size and a PASS
verdict; then synthesizes a 1x4 strip and asserts refusal. Prints a summary
and exits 0 only if all checks pass. Needs Pillow (it builds and processes
real images); without Pillow it exits 2.

## Provenance

The shipped `upstream-manifest.json` is a closed per-resource provenance
inventory. All shipped resources are original OMH; Pillow is not redistributed
here. See `LICENSE.upstream` for the original resource MIT license.
