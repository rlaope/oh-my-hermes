# geospatial-analysis Specialist Procedure

Expert clarification questions:
- `input and overlay polygon layers`
  - English: Which two polygon layers, source permissions, and study extent define the overlap question?
  - Korean: Which two polygon layers, source permissions, and study extent define the overlap question?
- `explicit source and metric target CRS`
  - English: What are the authoritative source CRS declarations and an appropriate projected metre CRS for measurement?
  - Korean: What are the authoritative source CRS declarations and an appropriate projected metre CRS for measurement?
- `new output directory and execution budget`
  - English: Which new directory receives outputs, which optional backend is installed, and what host timeout bounds execution?
  - Korean: Which new directory receives outputs, which optional backend is installed, and what host timeout bounds execution?

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
