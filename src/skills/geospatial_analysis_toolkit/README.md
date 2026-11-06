# Optional geospatial analysis toolkit

Original OMH helpers and synthetic fixtures, MIT, copyright 2026 oh-my-hermes
contributors. No upstream GIS-MCP code is copied. The implemented backend is
**direct Shapely/PyProj**; GIS-MCP, GeoPandas and Rasterio are not required or
claimed exercised. Loading/installing the skill reads text only and does not
install packages or execute a helper.

## Operator setup and command

Requires Python 3.11+ and optional `shapely>=2.0` plus `pyproj>=3.6` in a separate
operator-owned environment. Explicit setup example (not auto-run by OMH):

```sh
uv venv --python 3.12 /your/scratch/gis-venv
uv pip install --python /your/scratch/gis-venv/bin/python shapely pyproj
```

Run from this toolkit's directory using that interpreter and a finite host
terminal timeout (suggested fixture cap: 60 seconds):

```sh
/your/scratch/gis-venv/bin/python scripts/analyze.py \
  --input examples/input.json --overlay examples/overlay.json \
  --input-crs EPSG:3857 --overlay-crs EPSG:3857 --target-crs EPSG:3857 \
  --output-dir /your/scratch/new-gis-result
```

`--help` needs only stdlib. All three CRS flags are mandatory, accept explicit
`EPSG:<positive integer>` identifiers and never infer CRS from coordinates.
The source files may use different CRS; supported legacy embedded named CRS
must agree with the flags. A geographic or feet-based measurement target is
refused. Pick an appropriate projected metre CRS for the study extent: this
helper does not choose a scientifically suitable projection for you.
EPSG:3857 here is only a local synthetic analytical coordinate plane, not an
area-preserving recommendation for real-world data: Web Mercator and Mercator
inflate area by 1/cos^2(latitude), about 1.6x at 38 degrees, so the helper
refuses them as the target CRS unless both layers are the shipped example
files (checked by their digests); never add or edit `data_class` or `fixture_id` on your own layer to pass
that check. World Equidistant Cylindrical (EPSG:4087) is not equal-area either. For real layers use an equal-area CRS for the study extent (for
example EPSG:6933, or a regional Albers or Lambert azimuthal equal-area CRS),
or the local UTM zone or national projected grid for a small extent, and state
the choice in the report.

## Supported inputs and refusal

- UTF-8 GeoJSON FeatureCollections containing 1–1000 nonempty 2D Polygon or
  MultiPolygon Features; properties must be an object or null.
- At most 4 MiB and 100000 coordinate positions per layer; at most 100000
  candidate feature pairs. These caps do not replace the host execution timeout.
- Fixed result budget: **8 MiB (8,388,608 bytes)** for the complete pretty-printed
  `result.geojson`, including UTF-8/JSON escaping, indentation and final newline;
  at most **100000 result coordinate positions** across positive-area pairs.
  Properties are checked before backend import and charged again for every pair.
  Each pair must fit the remaining exact byte budget before it is retained; source
  properties stay referenced in memory, not deep-copied. Strings are measured in
  chunks of at most 4096 source characters, not by serializing the whole property
  tree/result first. Result nesting must fit 64 levels (root is level zero).
  Geometry position admission occurs before coordinate-array/mapping copies.
  Each metadata file (`summary.json` and `manifest.json`) is separately capped
  at **256 KiB (262,144 bytes)** before serialization, including its final newline.
  The three output bodies therefore total at most 8,912,896 bytes.
  Over-budget input/result exits 2 with no output directory or success manifest;
  nothing is silently truncated, dropped or replaced. There is no limit-raising
  flag. Reduce/split inputs explicitly, preserving the intended scientific scope.
  These are output/retained-result limits, **not** a hard process-RSS limit or a
  guarantee against native GEOS/PROJ transient allocations during an operation.
- Numeric finite coordinates, closed rings, valid topology and explicit CRS.
  Geographic source coordinates use longitude then latitude and must be within
  [-180,180]/[-90,90]. Antimeridian-spanning polygons require preprocessing.
- No geometry repair. Mixed polygon/line positive-area intersection collections
  are rejected rather than silently dropping components. Zero-area touch-only
  pairs are counted separately. Pair intersections are actual Shapely operations.
- Input/output paths may not contain traversal or symlink components; the
  only links accepted are macOS's own `/etc`, `/tmp` and `/var` into `/private`.
  The output directory must be new and its parent must already exist; no
  overwrite flag exists. Not a defense against a concurrently hostile
  filesystem writer.
- Dependency, input, CRS or geometry failure exits 2 without creating output.
  An I/O failure after computation can leave partial output, never an intentional
  success receipt; require exit zero and inspect all artifacts. PROJ networking
  is disabled and no external service or process is launched.

## Outputs and measured meaning

- `result.geojson`: actual positive-area pair intersections in OGC:CRS84
  longitude/latitude, no legacy `crs` member, with `input_index`, `overlay_index`,
  `input_properties`, `overlay_properties`, `area_m2` and `perimeter_m`.
- `summary.json` (`geospatial_summary/v1`): feature/touch-only counts, metric CRS,
  pair area/perimeter sums, unique union area and limitations. Pair sums may
  double-count overlapping sources; union area measures unique coverage.
- `manifest.json` (`geospatial_manifest/v1`): actual backend/GEOS/PROJ versions,
  UTC timestamp, interpreter/platform, raw input/output hashes, script digest and
  replay argv and fixed `resource_budget` limits/actual result byte count. Change
  `--output-dir` to a new directory to replay. The manifest
  excludes its own hash; hash it separately when retaining evidence.

Read the files back and verify actual bytes, geometry and measured values, not
just the success message. Metric measures are planar in the declared projection,
not geodesic ground truth. No map, raster, NoData, buffer, nearest-distance or
spatial-statistics output is implemented or promised.

## Declared synthetic analytical fixture

`examples/input.json` contains boxes [0,0,10,10] and [20,0,30,10];
`examples/overlay.json` contains [5,-5,25,15]. All are declared synthetic in
EPSG:3857 metres. The two intersection boxes are [5,0,10,10] and [20,0,25,10].
Expected: 2 output Features, 50 m² and 30 m perimeter each, pair/union area
100 m², pair perimeter 60 m, 0 touch-only pairs. Empty or missing computation
is not interchangeable with an observed zero-area intersection. Synthetic
numbers cannot establish public-world flood risk or site suitability.

The shipped `upstream-manifest.json` is a closed per-resource provenance
inventory. All shipped resources are original OMH; native dependencies are not
redistributed here. See `LICENSE.upstream` for the original resource MIT license.
