# Geospatial execution and QA

Read `toolkit/README.md` for the standalone command and fixture. The implemented
backend is **direct Shapely/PyProj**, not GIS-MCP. The helper performs actual
pairwise positive-area Polygon/MultiPolygon intersection. No map or raster is
promised. Skill loading and resource materialization only read inert text.

## Before execution

- Confirm source rights, study extent, longitude/x then latitude/y ordering and
  each explicit `EPSG:<integer>` CRS. The helper never guesses a source CRS;
  flags are mandatory even when legacy embedded CRS metadata exists, and any
  embedded declaration must agree. Input and overlay may have different CRS.
- Choose an appropriate projected metre CRS. Area and perimeter are planar in
  that CRS, not automatically equal-area, geodesic or ground-truth measurements.
  EPSG:3857 is used only for the declared local synthetic fixture, not a general
  recommendation for public-world measurement: the helper refuses Web Mercator and
  Mercator for any layer that is not the shipped fixture, because they
  inflate area by 1/cos^2(latitude); never add or edit `data_class` or `fixture_id`
  on a real layer to pass that check. Use an equal-area CRS for the extent or the
  local UTM zone / national grid. Geographic and feet-based target
  CRS are refused. Geographic inputs must be reprojected before measurement.
- Require finite 2D Polygon/MultiPolygon coordinates, closed rings, nonempty
  valid geometry and a bounded candidate-pair budget. No automatic `make_valid`
  or `buffer(0)` repair. Geographic ranges and antimeridian-spanning polygons
  are checked; unsupported mixed intersection geometry fails closed.
- The fixed helper budget is 8 MiB for the complete escaped/indented result,
  100000 retained result positions and 64 output JSON nesting levels; each metadata
  file is capped at 256 KiB before serialization. Properties
  are prechecked and charged per pair before retention/whole-result serialization;
  no attributes or results are silently dropped. There is no budget-raising flag.
  This bounds retained output, not native process RSS; keep the host timeout.
- Use a new output directory with an existing parent and no symlinks. A refused
  validation/dependency/CRS operation creates no output. An I/O failure after
  computation can leave partial files; absent `manifest.json` is not success.
  Do not publish sensitive locations through a shared evidence receipt.

## Execute and inspect

Use the host's bounded terminal tool, suggested 60 s for the fixture; the helper
cannot promise to interrupt arbitrary native geometry work itself. Optional
libraries are installed only with explicit setup consent in a separate environment;
no credential, network, subprocess launcher or core dependency is needed.

Record argv, interpreter, stdout, stderr and exit. `--help` works without optional
libraries; `python -I -S analyze.py ...` with valid input must refuse missing
`shapely`/`pyproj` and create no result. Missing dependencies, timeout and invalid
input are not observed zero-overlap findings. PROJ networking is disabled.

On exit zero, read `result.geojson`, `summary.json` and `manifest.json` back.
GeoJSON output uses OGC:CRS84 (longitude/latitude) without a legacy `crs` member;
metric properties and the summary name the measurement CRS separately. Each
positive-area source pair becomes one result Feature, including MultiPolygon
pairs; touch-only pairs are counted but do not become areal features. Source
properties are namespaced under `input_properties`/`overlay_properties` and source
indices are zero-based. Pair sums can double-count coverage when source polygons
overlap; `union_area_m2` measures unique coverage. A real empty intersection is
zero only after successful computation.

Recompute hashes using actual file bytes and inspect result coordinates, not just
stdout. For the original synthetic fixture: input rectangles [0,0,10,10] and
[20,0,30,10], overlay [5,-5,25,15], all in EPSG:3857 metres. Intersections are
[5,0,10,10] and [20,0,25,10]: 2 Features, 50 m² each, unique and pair area 100 m²,
30 m perimeter each, pair perimeter 60 m. This is deterministic analytical QA,
not public-world flood-risk, site suitability or facility evidence.

The manifest records actual library/engine versions, input/output hashes,
script digest, timestamp and replay argv. Replay requires a new output directory;
retain the original receipt rather than overwrite it. Reproducibility is bounded
by input bytes, CRS database, library versions and platform, not universal byte
identity. Keep advanced raster, NoData, buffer, nearest-distance, mapping and
spatial-statistical claims out until separately implemented and exercised.
