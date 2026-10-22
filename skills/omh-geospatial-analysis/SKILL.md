---
name: "omh-geospatial-analysis"
description: "[omh] Spatial layers to intersect: execute CRS-safe polygon overlay with measured areas, validated geometry and reproducible GeoJSON outputs. Use when the user says: geospatial-analysis, geospatial overlay, spatial intersection, intersect geojson layers, compute overlap area."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, analysis]
    category: analysis
    phase: spatial-computation
    role: operator
    quality_tier: execution-evidence-gated
    related_skills: [omh-data-analysis, omh-web-research]
---

# Geospatial Analysis

Required: input and overlay polygon layers, explicit source and metric target CRS, new output directory and execution budget. Output: result GeoJSON, measured summary JSON, replay and provenance manifest.

**HOLD:** Missing inputs or failed contract gates. Prepared OMH routing is not execution or approval.

## Why This Exists

Polygon computations can return plausible but wrong numbers when CRS, coordinate units or geometry are invalid. This skill couples fail-closed checks to a runnable optional overlay producer and inspectable replay artifacts.

## First Steps

- Read `toolkit/README.md` and `references/execution-and-qa.md` before executing `toolkit/scripts/analyze.py`; installation and skill discovery never run it.
- Confirm the two layers, explicit EPSG declarations, study extent, projected metre CRS, output directory and finite host timeout; never guess a missing CRS.
- Use the original synthetic rectangle fixture only for backend QA; do not describe it as a public flood, facility or site-suitability finding.

Contract: `references/full-contract.md`, loaded before analysis. Procedure: `references/procedure.md`. These are working methods, not an OMH runtime operation.

## Safety Rules

- Never infer CRS from plausible coordinates. Explicit source flags are mandatory; embedded declarations must agree.
- Refuse geographic-degree area/distance and non-metre targets; choose a suitable local/equal-area projected CRS rather than treating map units as ground truth.
- Do not auto-install optional libraries, import the companion on skill load, open a network connection, silently repair invalid geometry or overwrite existing outputs.
- No result is observed until the actual domain backend exits successfully and its output files are inspected. Missing backend, validation failure and timeout are not zero-overlap findings.
- Keep confidential locations and source data out of shared reports; carry only permitted evidence references. No map, raster/NoData, buffer, spatial statistics or nearest-distance capability is promised.

## When to Use

Use when supplied polygon layers need actual intersection and measured overlap, not a narrative report or a decorative map.

Strong routing signals: `geospatial-analysis`, `geospatial overlay`, `spatial intersection`, `intersect geojson layers`, `compute overlap area`

## Catalog Metadata

Category: `analysis`
Phase: `spatial-computation`
Hermes role: `operator`
Quality tier: `execution-evidence-gated`

## Completion Checklist

- Source declarations and metric target are explicit; invalid geometry is rejected, not silently repaired.
- The actual backend command and exit were observed; output GeoJSON, summary and manifest were read back and hashed, or the blocker is stated.
- Pair sums versus union area, projected measurement limits and synthetic versus public-world evidence remain distinct.

## Recovery Notes

- If CRS is missing, stop and ask for the authoritative declaration; do not assign one based on numeric range.
- If dependencies are missing, return a nonzero failure and an explicit optional-environment setup recipe; never synthesize outputs.
- If geometry is invalid, report the failing layer and request approved preprocessing before rerunning; if output already exists, choose a new directory.

## Workflow Lane

- Current lane: **Research and company ops** (`product-docs`, `source-finder`, `web-research`, `research`, `model-optimization`, `inference-serving`, `model-finetuning`, `research-brief`, `+26 more`) - research, signals, ops, and briefings.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## Runtime Evidence

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
