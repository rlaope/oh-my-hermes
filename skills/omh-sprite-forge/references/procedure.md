# sprite-forge Specialist Procedure

Expert clarification questions:
- `grid sheet from the host image tool on flat #FF00FF`
  - English: Which host image tool produces the sheet, which grid (2x2, 2x3, ...) holds which pose, and is the background flat #FF00FF?
  - Korean: 어떤 이미지 도구로 시트를 만들고, 어떤 격자(2x2, 2x3 등)의 어느 칸에 어떤 포즈가 들어가며, 배경은 단색 #FF00FF인가요?
- `declared rows x cols, cell size and feet baseline`
  - English: What cell size and feet baseline (for example 512px cell, y=430) and which frames map to which game-data timings?
  - Korean: 게임이 기대하는 셀 크기와 발 기준선(예: 512px 셀, y=430)은 무엇이고, 어떤 프레임이 게임 데이터의 어떤 타이밍에 대응하나요?
- `new output directory and execution budget`
  - English: Which new directory receives frames, is optional Pillow installed in a separate environment, and what host timeout bounds the run?
  - Korean: 프레임을 담을 새 디렉터리는 어디이고, Pillow가 별도 환경에 설치돼 있으며, 실행 시간 제한은 얼마인가요?

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
