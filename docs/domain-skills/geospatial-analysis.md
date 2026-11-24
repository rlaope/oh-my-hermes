# Geospatial analysis: executable vector overlay and QA

## V-03 output-budget repair (2026-10-22)

**Scoped repair PASS; final integration and acceptance remain parent-owned.**
The original producer record below is historical, not a claim that the repaired
candidate's shared generated projections, built distribution or full suite passed.

The standalone direct-Shapely/PyProj helper now has fixed conservative limits:

- `result.geojson`: 8,388,608 bytes, including JSON escaping, pretty indentation
  and the final newline; at most 100000 retained result coordinate positions.
- `summary.json` and `manifest.json`: 262,144 bytes each, checked before their
  whole-value serialization. Total promised output bodies cannot exceed 8,912,896
  bytes. Result JSON nesting is limited to 64 levels, with root level zero.
- A bounded exact JSON byte counter measures strings in chunks of at most 4096
  source characters. Properties are prechecked before importing optional science
  libraries and charged again for each produced pair. A pair is admitted before
  retention; source properties remain references, not deep copies. Coordinate
  admission precedes intersection coordinate-array/mapping copies.
- Exceeding a budget exits 2 before creating the output directory or success
  manifest. No attributes/results are silently dropped or truncated, and no flag
  raises these limits. Operators must explicitly reduce/split the scientific task.
- These are serialized-output/retained-result budgets, not a process-RSS sandbox.
  GEOS/PROJ can allocate native transient geometry memory; the host timeout and
  existing input/position/pair limits remain necessary.

### Fresh verification of the repaired source

Evidence is retained only under
`$HOME/.hermes/cache/scratch/omh-domain-dag-evidence-20261022/repair-verify/gis-budget-fix/`.
`commands.jsonl` records literal argv, cwd, TMPDIR, UTC times, exits and stream
hashes; `probe_budget.py` instruments the actual helper, not a mock GIS backend.

| Gate | Observed outcome |
| --- | --- |
| Test-first modest 1 MiB/32-pair amplification regression | RED exit 1 (old helper returned success); GREEN exit 0 after repair. |
| Original immutable `verify/repro-gis` inputs (1,053,203 bytes) | Helper exit 2, no output directory/manifest, **zero whole-result serializations**; largest property-string serialization chunk 4096 characters. |
| Original probe memory observation | Tracemalloc peak 16,281,903 bytes; macOS maximum resident set 62,783,488 bytes, including Python and real native-library imports. These measurements are not universal ceilings. |
| Exact production byte boundary | CLI succeeds with exactly **8,388,608** output bytes and all eight source-property copies intact; one extra byte refuses with no new output and preserves the earlier manifest. |
| Adjacent negative cases | Oversized nested Unicode properties, excessive nesting, per-result coordinate cap and oversized manifest metadata refuse. Escaping/indentation sizes and the exact smaller fixture boundary reconcile against actual serialization. |
| Real optional suite | Exit 0: **31 tests, no skips**, including the original CRS, geometry, empty-overlap, metrics and integrity regressions. |
| Core plus source/safety-policy suites | Exit 0: **72 tests, 13 optional spatial skips**. Counts overlap the real suite and are not summed. |
| Actual shipped synthetic fixture | Exit 0; 2 Features, pair/union area 100 m², pair perimeter 60 m. Result is 1912 bytes. Result/summary bytes exactly match retained original producer outputs; actual hashes match the new manifest. |

Actual backend remains Shapely 2.2.0 / GEOS 3.14.1 and PyProj 3.8.0 / PROJ 9.8.1
in the already-existing isolated Python 3.12.13 GIS environment. No install,
core dependency or safety-allowlist change was made. Existing Shapely transform
deprecation warnings remain visible in in-process test logs; no runtime backend
migration is claimed.

Reproduction commands, from the checkout, always use
`TMPDIR=$HOME/.hermes/cache/scratch` and `PYTHONPATH=tests`:

```sh
EVIDENCE=$HOME/.hermes/cache/scratch/omh-domain-dag-evidence-20261022
OMH_GIS_RUN_REAL=1 "$EVIDENCE/gis/venv/bin/python" -m unittest test_geospatial_analysis_skill -v
# Exit 0: 31 tests.
OMH_GIS_RUN_REAL= .venv/bin/python -m unittest test_geospatial_analysis_skill test_broad_exception_policy test_handoff_safety_contract_enforcement -v
# Exit 0: 72 tests, 13 skips.
"$EVIDENCE/gis/venv/bin/python" -I "$EVIDENCE/repair-verify/gis-budget-fix/probe_budget.py" original-amplification NEW_TAG
# Expected helper exit 2; new evidence names, no result directory.
"$EVIDENCE/gis/venv/bin/python" -I "$EVIDENCE/repair-verify/gis-budget-fix/probe_budget.py" synthetic-smoke NEW_TAG
# Exit 0; choose a new tag for every replay.
```

The original verifier evidence, original 33,580,457-byte expansion output and
`negative_cases.py` were read-only and their before/after hashes match. New
`original-amplification-final-budget-evidence.json` and
`synthetic-smoke-final-budget-evidence.json` contain the actual readback.
Closed toolkit provenance hashes were re-derived from the repaired resources.
No shared generated file was modified: parent must regenerate affected tap,
portable/reference/distribution inventories, rebuild and independently accept the
repaired candidate. Historical full-suite failures/timeouts remain unresolved.

## Historical producer record (before V-03 repair)

Status: **producer PASS**, observed on 2026-10-22. Shared catalog/distribution
integration and independent acceptance remain pending. This is a runnable optional
toolkit, not a report-only workflow card. Actual backend: **direct Shapely/PyProj**,
not GIS-MCP. GeoPandas and Rasterio were not needed or claimed exercised.

## Delivered boundary

`src/skills/geospatial_analysis_skill.py` exports `DEFINITION`,
`geospatial_analysis_definition()`, `REFERENCE_TEXT`,
`geospatial_analysis_reference_templates()`, `TOOLKIT_RESOURCES`,
`geospatial_analysis_support_templates()` and
`geospatial_analysis_provenance_manifest()` under the upstream contract.
The compact generic renderer retains the toolkit/execution-reference pointers;
the execution reference is original English guidance. Procedure input/output/check
refs resolve. No new registered OMH artifact API or core execution command exists.

`toolkit/scripts/analyze.py` performs real positive-area polygon pair intersection,
using explicit source CRS and a projected metre target. It rejects missing or
conflicting CRS, invalid/non-finite/3D geometry, geographic-degree and feet-based
measurements, unsafe paths and existing output directories. It never repairs
geometry silently, installs packages, spawns a subprocess or queries a service.
PROJ network access is disabled. Input layers may have different source CRS.

Outputs are actual `result.geojson` in OGC:CRS84 longitude/latitude,
`summary.json` with metric pair area/perimeter and unique union area, and
`manifest.json` with actual versions, raw hashes, settings and replay argv.
Pair sums and unique coverage have different meanings. Touch-only pairs are
counted separately, not reported as areal Features. No map, raster, NoData,
buffer, nearest-distance or spatial-statistics capability is promised.

## Closed resource inventory

Paths below are relative to `src/skills/geospatial_analysis_toolkit/`; emitted
support paths add `toolkit/`:

1. `README.md`
2. `LICENSE.upstream` (original OMH MIT terms; explicitly not copied GIS-MCP code)
3. `scripts/analyze.py`
4. `examples/input.json`
5. `examples/overlay.json`
6. `upstream-manifest.json`

The factory reads precisely this inventory through `importlib.resources`, caps
UTF-8 resources at 1 MiB, validates the exact provenance schema/inventory and each
resource digest, and never imports a companion or science dependency. All
resources are classified `original_omh`, with source/local hashes and no upstream
copied code. Original uncommitted content is identified by hashes rather than a
fictional upstream revision. The manifest excludes its own hash.

## Declared synthetic experiment and independent check

The shipped original fixture contains input rectangles [0,0,10,10] and
[20,0,30,10], intersected by overlay [5,-5,25,15], in EPSG:3857 metres.
Independent analytical intersections are [5,0,10,10] and [20,0,25,10]. Expected
and observed: **2 Features, 50 m² and 30 m perimeter each; 100 m² pair/union area,
60 m pair perimeter, 0 touch-only pairs**.

The isolated backend emitted actual GeoJSON. The evidence verifier read it back,
converted its longitude/latitude coordinates using an independent spherical
Mercator equation (not a GIS library), checked all four vertices for each expected
box within 1e-7 m, and used shoelace area and Euclidean perimeter. It obtained
50.000000000190994 m² per box and approximately 30.0000000000764 m perimeter;
summary values are exactly 50/30 per Feature and 100/60 in aggregate. All actual
input, output and script hashes reconciled with the manifest. The fixture is
**synthetic analytical QA, not a public-world finding**. EPSG:3857 is not recommended
as a general real-world area projection.

## Observed isolated environment and provenance

Evidence root:
`$HOME/.hermes/cache/scratch/omh-domain-dag-evidence-20261022/gis/`.
Setup commands (each exit 0; no science dependency added to core):

```sh
export TMPDIR=$HOME/.hermes/cache/scratch
EVIDENCE=$HOME/.hermes/cache/scratch/omh-domain-dag-evidence-20261022/gis
uv venv --python 3.12 "$EVIDENCE/venv"
uv pip install --python "$EVIDENCE/venv/bin/python" shapely pyproj
```

Observed Python 3.12.13; Shapely 2.2.0 / GEOS 3.14.1; PyProj 3.8.0 / PROJ 9.8.1.
Transitive packages: NumPy 2.5.4 and certifi 2026.10.19. Installed distribution
metadata identifies Shapely as BSD-3-Clause and PyProj as MIT; dependency-provenance
retains all installed license-file paths and hashes, including GEOS/PROJ notices.
No upstream source/data is redistributed by this toolkit. The core test interpreter
was the checkout's existing Python 3.14.7 environment; source policy and ordinary
unit tests do not need science libraries.

## Reproducible command and observed exits

From `$HOME/.hermes/cache/scratch/omh-domain-dag-20261022`:

```sh
export TMPDIR=$HOME/.hermes/cache/scratch
EVIDENCE=$HOME/.hermes/cache/scratch/omh-domain-dag-evidence-20261022/gis
KIT="$PWD/src/skills/geospatial_analysis_toolkit"
"$EVIDENCE/venv/bin/python" -I "$KIT/scripts/analyze.py" \
  --input "$KIT/examples/input.json" --overlay "$KIT/examples/overlay.json" \
  --input-crs EPSG:3857 --overlay-crs EPSG:3857 --target-crs EPSG:3857 \
  --output-dir "$EVIDENCE/result-final"
# Observed exit 0. For replay choose another NEW output directory.
```

Verification commands/results:

```sh
TMPDIR=$HOME/.hermes/cache/scratch PYTHONPATH=tests uv run python -m unittest tests.test_geospatial_analysis_skill -v
# Exit 0: 23 discovered/unique tests, 16 passed, 7 optional backend tests skipped.
TMPDIR=$HOME/.hermes/cache/scratch PYTHONPATH=tests OMH_GIS_RUN_REAL=1 "$EVIDENCE/venv/bin/python" -m unittest tests.test_geospatial_analysis_skill -v
# Exit 0: all 23 passed, no skips. No mocked engine satisfies this gate.
TMPDIR=$HOME/.hermes/cache/scratch PYTHONPATH=tests uv run python -m unittest tests.test_broad_exception_policy tests.test_handoff_safety_contract_enforcement -q
# Exit 0: 41 tests, OK; source safety allowlists unchanged.
TMPDIR=$HOME/.hermes/cache/scratch .venv/bin/python -I -S "$KIT/scripts/analyze.py" --help
# Exit 0 without site packages.
TMPDIR=$HOME/.hermes/cache/scratch .venv/bin/python -I -S "$KIT/scripts/analyze.py" --input "$KIT/examples/input.json" --overlay "$KIT/examples/overlay.json" --input-crs EPSG:3857 --overlay-crs EPSG:3857 --target-crs EPSG:3857 --output-dir "$EVIDENCE/missing-result"
# Exit 2: actionable missing shapely/pyproj message; missing-result does not exist.
TMPDIR=$HOME/.hermes/cache/scratch uv run --group lint ruff check src/skills/geospatial_analysis_skill.py src/skills/geospatial_analysis_toolkit/scripts/analyze.py tests/test_geospatial_analysis_skill.py
# Exit 0: All checks passed.
TMPDIR=$HOME/.hermes/cache/scratch uv run python -m compileall -q src/skills/geospatial_analysis_skill.py src/skills/geospatial_analysis_toolkit/scripts/analyze.py tests/test_geospatial_analysis_skill.py
# Exit 0.
TMPDIR=$HOME/.hermes/cache/scratch PYTHONPATH=tests uv run python -m unittest tests.test_show_reel_support_files tests.test_render_skill_pack -q
# Exit 0: 7 existing regression tests, OK.
```

The out-of-repo `run_verify.py --result-dir result-final` actually executed the
focused suites, source policy, help, missing-dependency refusal and real backend
smoke with finite subprocess timeouts. `command-receipts.json` contains literal
argv, cwd, environment, UTC start/finish and exits; matching stdout/stderr logs are
retained. `test-counts.json` independently cross-checks rendered test IDs against
unittest's testsRun. Use a new `--result-dir` if rerunning this verifier.

Evidence files include:

- `result-final/result.geojson`, `result-final/summary.json`, `result-final/manifest.json`
- `verification.json`, `command-receipts.json`, `test-counts.json`, `run_verify.py`
- `dependency-provenance.json`, `freeze.stdout.log`, and command-specific stdout/stderr logs
- The earlier `result/` smoke remains as a separate successful observation.

## Integration still owned by parent

No shared registration or generated projection was edited, and no commit was made.
The shared implementation contract's integration table remains binding:

- Import `DEFINITION` into `catalog_definitions.py`; add the reference factory to
  `skill_record.py`'s `REFERENCE_PRODUCERS` and the support factory to the common registry.
- Generalize `SkillRecord.support()`, native support ownership/stale cleanup and
  local-source converter from show-reel-only to finite declared per-owner resources.
- Add all six exact toolkit resources to wheel/sdist package-data, portable
  support paths, LF attributes and tap actual-file discovery; preserve owner names.
  Register `references/execution-and-qa.md` plus generic full-contract/procedure
  portable references. Do not recursively trust a source manifest.
- Add awareness lane/context-card, routing policies, action labels/acks/dedicated
  operations card/direct-workflow entry, harness/exposure wiring as needed; use
  existing normalized whole-phrase routing and positive/negative corpora. Leave
  Korean trigger tables frozen; live Korean semantic nomination was not tested.
- Positive: “Intersect these two GeoJSON layers in a metric CRS and compute overlap
  area.” Negative: “Explain the map metaphor in this essay; only plot existing CSV
  totals without spatial computation.” Generic table work stays `data-analysis`.
- Regenerate catalog/tap/portable/six-host projections and legitimate count/digest
  fixtures. Prove source-hidden wheel and sdist resources, native/portable/tap/
  local-source parity, fresh/upgrade/edited/unowned/stale ownership, full suite,
  routing/deference/density/procedure/navigation and release-drift gates.

The heavy reasoning demand is justified by executable validation, optional native
integrations and actual isolated QA, not extra prose. Production GIS suitability
still requires an appropriate real study projection, source permissions and
world-data validation; neither the synthetic smoke nor passing old distribution
tests establish those facts. Full-suite and distribution integration were not
claimed by this producer.
