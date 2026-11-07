# geospatial-analysis Specialist Procedure

Expert clarification questions:
- `input and overlay polygon layers`
  - English: Which two polygon layers, source permissions, and study extent define the overlap question?
  - Korean: 겹침을 구할 두 폴리곤 레이어는 무엇이고, 사용 권한과 분석 범위는 어떻게 되나요?
- `explicit source and metric target CRS`
  - English: What are the authoritative source CRS declarations and an appropriate projected metre CRS for measurement?
  - Korean: 각 레이어의 공식 좌표계(CRS) 선언은 무엇이고, 면적을 잴 미터 단위 투영 좌표계는 무엇으로 할까요?
- `new output directory and execution budget`
  - English: Which new directory receives outputs, which optional backend is installed, and what host timeout bounds execution?
  - Korean: 결과를 쓸 새 폴더는 어디이고, 어떤 선택 백엔드가 설치되어 있으며, 실행 제한 시간은 얼마인가요?

## Procedure

Declared checks:
- `gis_input_check`
  - Required result fields: `layer_hashes`, `source_crs`, `geometry_validity`, `target_units`
  - Criterion: Reject missing/conflicting CRS, invalid or non-finite geometry and geographic-degree measurement. Do not repair geometry silently.
- `gis_backend_check`
  - Required result fields: `backend`, `versions`, `command`, `exit_code`
  - Criterion: Name the actual backend and versions; use direct Shapely/PyProj when sufficient. Missing dependencies or timeout must never produce guessed results.
- `gis_output_check`
  - Required result fields: `result_count`, `pair_area_sum_m2`, `union_area_m2`, `output_hashes`, `fixture_limits`
  - Criterion: Read back actual output geometry, summary and manifest, reconcile count/area independently and distinguish overlapping pair sums from unique coverage.

### `gis_validate` (analysis)

Inspect source rights, coordinate ordering and extent; require explicit EPSG identifiers and an appropriate projected metre CRS before preparing computation.

- Input refs: `input and overlay polygon layers`, `explicit source and metric target CRS`
- Output refs: `replay and provenance manifest`
- Check IDs: `gis_input_check`

### `gis_intersect` (production)

Run the standalone helper with a finite host timeout in an isolated optional environment; record real stdout, stderr and exit without fallback values.

- Input refs: `input and overlay polygon layers`, `explicit source and metric target CRS`, `new output directory and execution budget`
- Output refs: `result GeoJSON`, `measured summary JSON`, `replay and provenance manifest`
- Check IDs: `gis_input_check`, `gis_backend_check`
- If this step fails: not_observed; still stands: `replay and provenance manifest`; hand back: Return the replay and provenance manifest, captured stdout, stderr and exit or timeout, and the dependency or input blocker for a retry in a new output directory without claiming zero overlap.

### `gis_reconcile` (validation)

Read back every promised artifact, check hashes and independent area/count expectations, and report observed results separately from public-world interpretation.

- Input refs: `input and overlay polygon layers`, `explicit source and metric target CRS`, `new output directory and execution budget`
- Output refs: `result GeoJSON`, `measured summary JSON`, `replay and provenance manifest`
- Check IDs: `gis_output_check`, `gis_backend_check`
- If this step fails: tentative; still stands: `replay and provenance manifest`; hand back: Return result GeoJSON and measured summary JSON with failed hash, count or pair-sum versus union-area checks and fixture limits; retain only the manifest's validated input provenance, not a verified overlap result.
