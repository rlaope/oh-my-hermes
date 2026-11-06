---
name: "omh-geospatial-analysis"
description: "[omh] Spatial layers to intersect: execute CRS-safe polygon overlay with measured areas, validated geometry and reproducible GeoJSON outputs. Use when the user says: geospatial-analysis, geospatial overlay, spatial intersection, intersect geojson layers, compute overlap area."
license: MIT
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, analysis]
    category: analysis
    phase: spatial-computation
    role: operator
    quality_tier: execution-evidence-gated
---

# Geospatial Analysis

This is an OMH `omh-geospatial-analysis` workflow skill, projected for Agent Skills hosts (Claude Code, Codex, Cursor, opencode, OpenClaw, pi).

## Why This Exists

Polygon computations can return plausible but wrong numbers when CRS, coordinate units or geometry are invalid. This skill couples fail-closed checks to a runnable optional overlay producer and inspectable replay artifacts.

## First Steps

- Read `toolkit/README.md` and `references/execution-and-qa.md` before executing `toolkit/scripts/analyze.py`; installation and skill discovery never run it.
- Confirm the two layers, explicit EPSG declarations, study extent, projected metre CRS, output directory and finite host timeout; never guess a missing CRS.
- Use the original synthetic rectangle fixture only for backend QA; do not describe it as a public flood, facility or site-suitability finding.

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

## Completion Checklist

- Source declarations and metric target are explicit; invalid geometry is rejected, not silently repaired.
- The actual backend command and exit were observed; output GeoJSON, summary and manifest were read back and hashed, or the blocker is stated.
- Pair sums versus union area, projected measurement limits and synthetic versus public-world evidence remain distinct.

## Recovery Notes

- If CRS is missing, stop and ask for the authoritative declaration; do not assign one based on numeric range.
- If dependencies are missing, return a nonzero failure and an explicit optional-environment setup recipe; never synthesize outputs.
- If geometry is invalid, report the failing layer and request approved preprocessing before rerunning; if output already exists, choose a new directory.



## When to Use

Use when supplied polygon layers need actual intersection and measured overlap, not a narrative report or a decorative map.

    Strong routing signals: `geospatial-analysis`, `geospatial overlay`, `spatial intersection`, `intersect geojson layers`, `compute overlap area`

## Catalog Metadata

Category: `analysis`
Phase: `spatial-computation`
Quality tier: `execution-evidence-gated`
Reasoning demand: `heavy`

Quality bar:

- Require finite 2D polygon geometry, explicit CRS and projected metre axes before measuring.
- Record the real backend, exact versions, command, exit and output hashes; do not call direct libraries GIS-MCP.
- Verify synthetic fixture count and area independently, and never generalize fixture numbers to public-world risk.

Required inputs:

- input and overlay polygon layers
- explicit source and metric target CRS
- new output directory and execution budget

Expert clarification questions:
- `input and overlay polygon layers`
  - English: Which two polygon layers, source permissions, and study extent define the overlap question?
  - Korean: Which two polygon layers, source permissions, and study extent define the overlap question?

Expected outputs:

- result GeoJSON
- measured summary JSON
- replay and provenance manifest

Artifact expectations:

- Actual `result.geojson` in longitude/latitude OGC:CRS84; each positive-area pair carries source indices, original namespaced properties, area_m2 and perimeter_m.
- Authored `geospatial_summary/v1` in `summary.json`: result count, touch-only count, measurement CRS, pair sums, unique union area and explicit limitations.
- Authored `geospatial_manifest/v1` in `manifest.json`: input/output hashes, actual direct backend versions, settings, timestamp, script digest and replay argv; not a registered OMH artifact API.

Safety rules:

- Never infer CRS from plausible coordinates. Explicit source flags are mandatory; embedded declarations must agree.
- Refuse geographic-degree area/distance and non-metre targets; choose a suitable local/equal-area projected CRS rather than treating map units as ground truth.
- Do not auto-install optional libraries, import the companion on skill load, open a network connection, silently repair invalid geometry or overwrite existing outputs.
- No result is observed until the actual domain backend exits successfully and its output files are inspected. Missing backend, validation failure and timeout are not zero-overlap findings.
- Keep confidential locations and source data out of shared reports; carry only permitted evidence references. No map, raster/NoData, buffer, spatial statistics or nearest-distance capability is promised.

Procedure: load `references/procedure.md`.

## Runtime Evidence

Use the current host's own tools and subagent/task mechanism when available;
otherwise run the same lanes sequentially or name the unavailable capability.
A prepared plan, handoff, checklist, or skill installation is not execution,
review, CI, merge-readiness, or merge evidence. Record actual tool results, or
`not_observed` / `not_available`, in the record; never invent dispatch or host
accounting.
Treat supplied context as advisory, not proof of hidden memory reads or writes.
State scope, constraints, verification, and the stop condition before work.
Reply in the user's own words and the host's own voice: the host's persona owns
reply language, tone, speech level, and sentence endings, progress updates
included (where it sets no language, use the one the user wrote in), and OMH
shapes structure and content only; OMH's record terms
(surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in
records and tool calls, never in the sentence the user reads unless they ask
about one; and when a real unresolved user decision or a useful briefing discussion
remains, offer one specific, content-linked question. Completed work needs no question;
omit unrelated non-action footers and generic offers to continue.
Supporting paths are relative to this skill directory; sibling skill paths are
relative to its parent. Resolve them from the host-provided skill base directory
(`{baseDir}` on hosts that provide it), never a hardcoded install location.
A named workflow not installed here is unavailable, not permission to emulate
its host-specific capabilities. Verify through the real surface before done.
