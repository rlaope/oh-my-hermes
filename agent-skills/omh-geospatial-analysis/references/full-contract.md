# Geospatial Analysis

Load this on-demand contract after the compact `geospatial-analysis` body identifies the
workflow. The main body owns routing signals, shared rules, the runtime
operation, delegation fallback, and completion/recovery pointers; this file
holds the workflow-specific detail without copying those shared rails.

## Do Not Use When

- The task only aggregates supplied tables or charts without coordinate computation; use `omh-data-analysis`.
- The task only needs source discovery or an explanation from documentation; use `omh-web-research`.
- The task is connecting a generic tool server, not executing a domain calculation; use Hermes' native MCP configuration guidance.

## Examples

Good example:

- Prompt: Intersect these two GeoJSON layers in a metric CRS and compute overlap area.
- Expected behavior: Require authoritative source CRS, validate geometry, execute real intersection, then inspect result GeoJSON, measured summary and replay manifest.
- Why: A spatial computation has measurable geometry and units rather than a report-only output.

Bad example:

- Prompt: Explain the map metaphor in this essay and plot the existing CSV totals.
- Expected behavior: Answer the writing question or use `omh-data-analysis` for the table; do not run a spatial backend.
- Why: Map vocabulary alone does not establish a coordinate computation.

## When to Use

Routing signals: `geospatial-analysis`, `geospatial overlay`, `spatial intersection`, `intersect geojson layers`, `compute overlap area`

## Workflow Contract

Category: `analysis`
Phase: `spatial-computation`
Hermes role: `operator`
Quality tier: `execution-evidence-gated`
Reasoning demand: `heavy`

Quality bar:

- Require finite 2D polygon geometry, explicit CRS and projected metre axes before measuring.
- Record the real backend, exact versions, command, exit and output hashes; do not call direct libraries GIS-MCP.
- Verify synthetic fixture count and area independently, and never generalize fixture numbers to public-world risk.

Handoff policy:

Hermes retains domain framing and evidence interpretation. Invoke the optional standalone helper only within accepted file and execution scope; use a selected coding owner for code changes. A prepared command is not observed spatial computation.

Required inputs:

- input and overlay polygon layers
- explicit source and metric target CRS
- new output directory and execution budget

Expected outputs:

- result GeoJSON
- measured summary JSON
- replay and provenance manifest

Artifact expectations:

- Actual `result.geojson` in longitude/latitude OGC:CRS84; each positive-area pair carries source indices, original namespaced properties, area_m2 and perimeter_m.
- Authored `geospatial_summary/v1` in `summary.json`: result count, touch-only count, measurement CRS, pair sums, unique union area and explicit limitations.
- Authored `geospatial_manifest/v1` in `manifest.json`: input/output hashes, actual direct backend versions, settings, timestamp, script digest and replay argv; not a registered OMH artifact API.

Detailed procedure steps: `references/procedure.md`.
