"""Canonical CRS-safe vector skill and closed, inert optional toolkit exports."""
from __future__ import annotations

import hashlib
from importlib.resources import files
import json

from .catalog_types import ExpertQuestion, ProcedureCheck, ProcedureBail, ProcedureStep, SkillDefinition, SkillExample

TOOLKIT_RESOURCES = (
    "README.md", "LICENSE.upstream", "scripts/analyze.py",
    "examples/input.json", "examples/overlay.json", "upstream-manifest.json",
)

_INPUTS = ("input and overlay polygon layers", "explicit source and metric target CRS", "new output directory and execution budget")
_OUTPUTS = ("result GeoJSON", "measured summary JSON", "replay and provenance manifest")

DEFINITION = SkillDefinition(
    name="geospatial-analysis",
    description="Spatial layers to intersect: execute CRS-safe polygon overlay with measured areas, validated geometry and reproducible GeoJSON outputs.",
    triggers=("geospatial-analysis", "geospatial overlay", "spatial intersection", "intersect geojson layers", "compute overlap area"),
    use_when="Use when supplied polygon layers need actual intersection and measured overlap, not a narrative report or a decorative map.",
    category="analysis", phase="spatial-computation", hermes_role="operator",
    delegation_boundary="retained-catalog-intent", progressive_disclosure=True,
    reasoning_demand="heavy",
    required_inputs=_INPUTS, expected_outputs=_OUTPUTS,
    expert_questions=tuple(ExpertQuestion(key, question, korean) for key, question, korean in (
        (_INPUTS[0], "Which two polygon layers, source permissions, and study extent define the overlap question?",
         "겹침을 구할 두 폴리곤 레이어는 무엇이고, 사용 권한과 분석 범위는 어떻게 되나요?"),
        (_INPUTS[1], "What are the authoritative source CRS declarations and an appropriate projected metre CRS for measurement?",
         "각 레이어의 공식 좌표계(CRS) 선언은 무엇이고, 면적을 잴 미터 단위 투영 좌표계는 무엇으로 할까요?"),
        (_INPUTS[2], "Which new directory receives outputs, which optional backend is installed, and what host timeout bounds execution?",
         "결과를 쓸 새 폴더는 어디이고, 어떤 선택 백엔드가 설치되어 있으며, 실행 제한 시간은 얼마인가요?"),
    )),
    opening_steps=(
        "Read `toolkit/README.md` and `references/execution-and-qa.md` before executing `toolkit/scripts/analyze.py`; installation and skill discovery never run it.",
        "Confirm the two layers, explicit EPSG declarations, study extent, projected metre CRS, output directory and finite host timeout; never guess a missing CRS. The helper reads GeoJSON only: for a shapefile, GeoPackage or KML ask for a GeoJSON export with the CRS stated, or offer a separately approved conversion (for example `ogr2ogr`).",
        "Use the original synthetic rectangle fixture only for backend QA; do not describe it as a public flood, facility or site-suitability finding.",
    ),
    handoff_policy="Hermes retains domain framing and evidence interpretation. Invoke the optional standalone helper only within accepted file and execution scope; use a selected coding owner for code changes. A prepared command is not observed spatial computation.",
    procedure_checks=(
        ProcedureCheck("gis_input_check", ("layer_hashes", "source_crs", "geometry_validity", "target_units"),
                       "Reject missing/conflicting CRS, invalid or non-finite geometry and geographic-degree measurement. Do not repair geometry silently."),
        ProcedureCheck("gis_backend_check", ("backend", "versions", "command", "exit_code"),
                       "Name the actual backend and versions; use direct Shapely/PyProj when sufficient. Missing dependencies or timeout must never produce guessed results."),
        ProcedureCheck("gis_output_check", ("result_count", "pair_area_sum_m2", "union_area_m2", "output_hashes", "fixture_limits"),
                       "Read back actual output geometry, summary and manifest, reconcile count/area independently and distinguish overlapping pair sums from unique coverage."),
    ),
    procedure_steps=(
        ProcedureStep("gis_validate", "analysis", (_INPUTS[0], _INPUTS[1]), (_OUTPUTS[2],), ("gis_input_check",),
                      "Inspect source rights, coordinate ordering and extent; require explicit EPSG identifiers and an appropriate projected metre CRS before preparing computation."),
        ProcedureStep("gis_intersect", "production", _INPUTS, _OUTPUTS, ("gis_input_check", "gis_backend_check"),
                      "Run the standalone helper with a finite host timeout in an isolated optional environment; record real stdout, stderr and exit without fallback values.",
            on_fail=ProcedureBail(
                still_stands=('replay and provenance manifest',),
                downgrade_to='not_observed',
                handback='Return the replay and provenance manifest, captured stdout, stderr and exit or timeout, and the dependency or input blocker for a retry in a new output directory without claiming zero overlap.',
            ),
        ),
        ProcedureStep("gis_reconcile", "validation", _INPUTS, _OUTPUTS, ("gis_output_check", "gis_backend_check"),
                      "Read back every promised artifact, check hashes and independent area/count expectations, and report observed results separately from public-world interpretation.",
            on_fail=ProcedureBail(
                still_stands=('replay and provenance manifest',),
                downgrade_to='tentative',
                handback="Return result GeoJSON and measured summary JSON with failed hash, count or pair-sum versus union-area checks and fixture limits; retain only the manifest's validated input provenance, not a verified overlap result.",
            ),
        ),
    ),
    artifact_expectations=(
        "Actual `result.geojson` in longitude/latitude OGC:CRS84; each positive-area pair carries source indices, original namespaced properties, area_m2 and perimeter_m.",
        "Authored `geospatial_summary/v1` in `summary.json`: result count, touch-only count, measurement CRS, pair sums, unique union area and explicit limitations.",
        "Authored `geospatial_manifest/v1` in `manifest.json`: input/output hashes, actual direct backend versions, settings, timestamp, script digest and replay argv; not a registered OMH artifact API.",
    ),
    safety_rules=(
        "Never infer CRS from plausible coordinates. Explicit source flags are mandatory; embedded declarations must agree.",
        "Refuse geographic-degree area/distance and non-metre targets; choose a suitable local/equal-area projected CRS rather than treating map units as ground truth.",
        "Do not auto-install optional libraries, import the companion on skill load, open a network connection, silently repair invalid geometry or overwrite existing outputs.",
        "No result is observed until the actual domain backend exits successfully and its output files are inspected. Missing backend, validation failure and timeout are not zero-overlap findings.",
        "Keep confidential locations and source data out of shared reports; carry only permitted evidence references. No map, raster/NoData, buffer, spatial statistics or nearest-distance capability is promised: for point, line, distance or buffer work, say the helper does not cover it and offer a separately approved Shapely/GeoPandas script under the same rules (explicit CRS, metre target, recorded versions).",
        "Web Mercator (EPSG:3857) and Mercator distort area (about 1.6x at 38 degrees latitude) and the helper refuses them for real layers: choose an equal-area CRS for the extent (for example EPSG:6933 or a regional Albers/LAEA) or the local UTM zone or national projected grid for a small extent, and state the choice in the report.",
    ),
    quality_tier="execution-evidence-gated",
    quality_bar=(
        "Require finite 2D polygon geometry, explicit CRS and projected metre axes before measuring.",
        "Record the real backend, exact versions, command, exit and output hashes; do not call direct libraries GIS-MCP.",
        "Verify synthetic fixture count and area independently, and never generalize fixture numbers to public-world risk.",
    ),
    why_this_exists="Polygon computations can return plausible but wrong numbers when CRS, coordinate units or geometry are invalid. This skill couples fail-closed checks to a runnable optional overlay producer and inspectable replay artifacts.",
    do_not_use_when=(
        "The task only aggregates supplied tables or charts without coordinate computation; use `data-analysis`.",
        "The task only needs source discovery or an explanation from documentation; use `web-research`.",
        "The task is connecting a generic tool server, not executing a domain calculation; use Hermes' native MCP configuration guidance.",
    ),
    good_example=SkillExample(
        "Intersect these two GeoJSON layers in a metric CRS and compute overlap area.",
        "Require authoritative source CRS, validate geometry, execute real intersection, then inspect result GeoJSON, measured summary and replay manifest.",
        "A spatial computation has measurable geometry and units rather than a report-only output."),
    bad_example=SkillExample(
        "Explain the map metaphor in this essay and plot the existing CSV totals.",
        "Answer the writing question or use `data-analysis` for the table; do not run a spatial backend.",
        "Map vocabulary alone does not establish a coordinate computation."),
    final_checklist=(
        "Source declarations and metric target are explicit; invalid geometry is rejected, not silently repaired.",
        "The actual backend command and exit were observed; output GeoJSON, summary and manifest were read back and hashed, or the blocker is stated.",
        "Pair sums versus union area, projected measurement limits and synthetic versus public-world evidence remain distinct.",
    ),
    recovery_notes=(
        "If CRS is missing, stop and ask for the authoritative declaration; do not assign one based on numeric range.",
        "If dependencies are missing, return a nonzero failure and an explicit optional-environment setup recipe; never synthesize outputs.",
        "If geometry is invalid, report the failing layer and request approved preprocessing before rerunning; if output already exists, choose a new directory.",
    ),
    situations=("two boundary files need a shared coverage measurement", "polygon areas look wrong after coordinate conversion", "which parcels overlap this declared footprint", "a boundary layer has no authoritative coordinate declaration", "overlapping pair sums differ from unique covered area"),
)

REFERENCE_TEXT = {"execution-and-qa": """# Geospatial execution and QA

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
  Mercator for any layer not declared `data_class` `synthetic`, because they
  inflate area by 1/cos^2(latitude). Use an equal-area CRS for the extent or the
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
"""}


def geospatial_analysis_definition():
    return DEFINITION


def geospatial_analysis_reference_templates():
    from .render import SkillReferenceTemplate, loadable_skill_mentions
    return [SkillReferenceTemplate(DEFINITION.name, f"references/{key}.md", loadable_skill_mentions(text))
            for key, text in REFERENCE_TEXT.items()]


def geospatial_analysis_provenance_manifest():
    """Generate hashes for reviewed original resources; this does not write them."""
    root = files("omh.skills").joinpath("geospatial_analysis_toolkit")
    entries = {}
    for relative in TOOLKIT_RESOURCES:
        if relative == "upstream-manifest.json":
            continue
        sha256 = hashlib.sha256(root.joinpath(relative).read_bytes()).hexdigest()
        entries[relative] = {"local_sha256": sha256, "source_sha256": sha256,
            "source_path": "src/skills/geospatial_analysis_toolkit/" + relative,
            "classification": "original_omh", "upstream": [], "license": "MIT",
            "copyright": "Copyright (c) 2026 oh-my-hermes contributors",
            "modification_notice": "Original OMH helper, synthetic example or guidance; no upstream source copied."}
    return {"schema": "omh_geospatial_analysis_provenance/v1",
        "repository": "https://github.com/rlaope/oh-my-hermes", "revision": None,
        "revision_note": "Original uncommitted resources identified by content hashes; not attributed to an upstream revision.",
        "license": "MIT", "self_hash": "excluded; outer distribution inventories hash this manifest", "files": entries}


def geospatial_analysis_support_templates():
    from .support_files import SkillSupportTemplate, validate_support_templates
    root = files("omh.skills").joinpath("geospatial_analysis_toolkit")
    texts = {}
    for relative in TOOLKIT_RESOURCES:
        resource = root.joinpath(relative)
        with resource.open("rb") as stream:
            raw = stream.read(1_048_577)
        if len(raw) > 1_048_576:
            raise ValueError("geospatial toolkit resource exceeds size limit")
        texts[relative] = raw.decode("utf-8")
    provenance = json.loads(texts["upstream-manifest.json"])
    expected = set(TOOLKIT_RESOURCES) - {"upstream-manifest.json"}
    if (not isinstance(provenance, dict) or provenance.get("schema") != "omh_geospatial_analysis_provenance/v1"
            or not isinstance(provenance.get("files"), dict) or set(provenance["files"]) != expected):
        raise ValueError("invalid closed geospatial provenance inventory")
    for relative in expected:
        entry = provenance["files"][relative]
        if not isinstance(entry, dict) or hashlib.sha256(texts[relative].encode("utf-8")).hexdigest() != entry.get("local_sha256"):
            raise ValueError(f"geospatial provenance digest mismatch: {relative}")
    return validate_support_templates([SkillSupportTemplate(DEFINITION.name, "toolkit/" + relative, texts[relative])
                                       for relative in TOOLKIT_RESOURCES])
