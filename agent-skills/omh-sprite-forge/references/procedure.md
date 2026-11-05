# sprite-forge Specialist Procedure

Expert clarification questions:
- `grid sheet from the host image tool on flat #FF00FF`
  - English: Which host image tool produces the sheet, which grid (2x2, 2x3, ...) holds which pose, and is the background flat #FF00FF?
  - Korean: Which host image tool produces the sheet, which grid (2x2, 2x3, ...) holds which pose, and is the background flat #FF00FF?
- `declared rows x cols, cell size and feet baseline`
  - English: What cell size and feet baseline (for example 512px cell, y=430) and which frames map to which game-data timings?
  - Korean: What cell size and feet baseline (for example 512px cell, y=430) and which frames map to which game-data timings?
- `new output directory and execution budget`
  - English: Which new directory receives frames, is optional Pillow installed in a separate environment, and what host timeout bounds the run?
  - Korean: Which new directory receives frames, is optional Pillow installed in a separate environment, and what host timeout bounds the run?

## Procedure

Declared checks:
- `sprite_input_check`
  - Required result fields: `grid_layout`, `background_key`, `cell_division`, `source_record`
  - Criterion: Refuse 1xN strips, inexact cell division, oversized files and wide effects packed into a character cell; put slashes and muzzle flashes on a separate sheet.
- `sprite_backend_check`
  - Required result fields: `pillow_version`, `command`, `exit_code`, `script_sha256`
  - Criterion: Name the real interpreter and Pillow version; missing Pillow, refusal exit 2 or timeout never yields guessed frames.
- `sprite_qc_check`
  - Required result fields: `body_scale_cv`, `anchor_y_std`, `verdict`, `output_hashes`
  - Criterion: Require body_scale_cv <= 0.08 and anchor_y_std <= 0.05; a REGENERATE verdict (exit 3) means a new source sheet, never hand-patched frames.

### `sprite_direct` (analysis)

Write the character art-direction record: identity elements, rejected drafts with reasons, cell size, baseline and attack-frame timing linked to game data.

- Input refs: `grid sheet from the host image tool on flat #FF00FF`, `declared rows x cols, cell size and feet baseline`
- Output refs: `character art-direction record`
- Check IDs: `sprite_input_check`

### `sprite_process` (production)

Run the helper with a finite host timeout: chroma key, cell split, component cleanup, one common scale, feet-baseline alignment and nearest-neighbor resize.

- Input refs: `grid sheet from the host image tool on flat #FF00FF`, `declared rows x cols, cell size and feet baseline`, `new output directory and execution budget`
- Output refs: `aligned equal-size frames and sheet`, `sprite_forge_qc/v1 receipt`, `character art-direction record`
- Check IDs: `sprite_input_check`, `sprite_backend_check`
- If this step fails: not_observed; still stands: `character art-direction record`; hand back: Return the character art-direction record and observed helper command, refusal or timeout, with the required grid correction or optional Pillow setup before retrying in a new output directory.

### `sprite_verify` (validation)

Read back every frame, the aligned sheet and qc.json; recompute hashes and report observed metrics separately from art-quality judgement.

- Input refs: `grid sheet from the host image tool on flat #FF00FF`, `declared rows x cols, cell size and feet baseline`, `new output directory and execution budget`
- Output refs: `aligned equal-size frames and sheet`, `sprite_forge_qc/v1 receipt`, `character art-direction record`
- Check IDs: `sprite_qc_check`, `sprite_backend_check`
- If this step fails: tentative; still stands: `character art-direction record`; hand back: Return the sprite_forge_qc/v1 receipt with observed metrics or read-back gaps and, for REGENERATE, the tighter pose and scale instructions for a new source sheet, never patched frames.
