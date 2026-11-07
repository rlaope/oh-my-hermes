# molecular-docking Specialist Procedure

Expert clarification questions:
- `prepared receptor and ligand PDBQT paths`
  - English: Which prepared, rights-cleared single-ligand and rigid-receptor PDBQT files are authorized?
  - Korean: 사용이 허가된, 준비를 마친 단일 리간드와 강체 수용체 PDBQT 파일은 무엇인가요?
- `binding box and preparation provenance`
  - English: What are the center and box dimensions in angstrom, and which protonation, charge, tautomer and preparation choices produced these files?
  - Korean: 박스 중심과 크기(옹스트롬)는 얼마이고, 어떤 양성자화, 전하, 호변이성질체, 준비 방식으로 이 파일들을 만들었나요?
- `approved local resource budget`
  - English: Which isolated optional backend, finite host deadline and new evidence directory are approved?
  - Korean: 승인된 격리 선택 백엔드, 유한한 호스트 제한 시간, 새 증거 폴더는 무엇인가요?

## Procedure

Declared checks:
- `docking_input_check`
  - Required result fields: `file_hashes`, `format_validation`, `source_license`, `preparation_choices`, `binding_box`
  - Criterion: Require safe new output paths, valid finite PDBQT atoms, rigid receptor/single ligand, rights and preparation provenance; HOLD absent binding center or preparation facts.
- `docking_budget_check`
  - Required result fields: `cpu`, `seed`, `exhaustiveness`, `n_poses`, `host_deadline`
  - Criterion: Require CPU 1-2, positive fixed seed, exhaustiveness 1-4, poses 1-5, box dimensions 1-24 angstrom and a host-enforced deadline at most 180 seconds; the helper records but cannot interrupt native code itself.
- `docking_execution_check`
  - Required result fields: `backend_identity`, `pose_score_readback`, `hashes`, `replay`, `claim_boundary`
  - Criterion: Require actual dock(), matching MODEL/ENDMDL and VINA RESULT records, finite energies in kcal/mol, engine version, stdout/stderr, exit/deadline evidence and digest-bound replay. A mock, score-only or optimize-only call cannot pass.

### `docking_scope` (analysis)

Bind rights-cleared prepared files, protonation/tautomer/charges, receptor assumptions, site and resource budget. Run optional --validate-only to read back input digests, never as completed docking.

- Input refs: `prepared receptor and ligand PDBQT paths`, `binding box and preparation provenance`, `approved local resource budget`
- Output refs: `molecular_docking_preflight/v1`
- Check IDs: `docking_input_check`, `docking_budget_check`

### `docking_execute` (production)

Explicitly run toolkit/scripts/dock.py in the chosen isolated Vina environment with a new output directory, captured logs and a real finite host timeout. Never auto-install or silently substitute a provider.

- Input refs: `prepared receptor and ligand PDBQT paths`, `binding box and preparation provenance`, `approved local resource budget`
- Output refs: `molecular_docking_run/v1 and real pose/score files`
- Check IDs: `docking_input_check`, `docking_budget_check`
- If this step fails: not_observed; still stands: `molecular_docking_preflight/v1`; hand back: Return molecular_docking_preflight/v1 with captured stdout, stderr, exit or deadline evidence and any partial pose/score files for backend review before a retry in a new output directory.

### `docking_verify` (validation)

Read poses.pdbqt, scores.json and manifest.json; reconcile saved pose energies and atom records with actual inputs and all hashes. Replay with a new output directory when needed; qualify reproducibility by version/platform.

- Input refs: `prepared receptor and ligand PDBQT paths`, `binding box and preparation provenance`, `approved local resource budget`
- Output refs: `molecular_docking_run/v1 and real pose/score files`
- Check IDs: `docking_execution_check`
- If this step fails: tentative; still stands: `molecular_docking_preflight/v1`; hand back: Return poses.pdbqt, scores.json and manifest.json with failed pose, energy, atom-record, hash or replay checks and engine version/platform limits; keep the docking run unverified.
