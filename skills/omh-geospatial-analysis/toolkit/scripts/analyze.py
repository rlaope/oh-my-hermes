#!/usr/bin/env python3
"""Original OMH optional polygon overlay helper; MIT, copyright 2026 OMH contributors."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import platform
from pathlib import Path
import re
import sys

MAX_BYTES = 4_194_304
MAX_FEATURES = 1000
MAX_POSITIONS = 100_000
MAX_PAIRS = 100_000
MAX_OUTPUT_BYTES = 8_388_608
MAX_METADATA_BYTES = 262_144
MAX_OUTPUT_POSITIONS = 100_000
MAX_JSON_DEPTH = 64


def parser():
    cli = argparse.ArgumentParser(description="Intersect polygon layers using explicit CRS and metric measurements.")
    cli.add_argument("--input", required=True)
    cli.add_argument("--overlay", required=True)
    cli.add_argument("--input-crs", required=True)
    cli.add_argument("--overlay-crs", required=True)
    cli.add_argument("--target-crs", required=True)
    cli.add_argument("--output-dir", required=True)
    return cli


def system_alias(part):
    # macOS ships /etc, /tmp and /var (home of the default temp dir) as links
    # into /private. Only root can create a top-level entry, so trust exactly
    # those three, and only when the link names the same directory there.
    if sys.platform != "darwin" or part.parent != Path("/") or part.name not in ("etc", "tmp", "var"):
        return False
    try:
        return os.readlink(part) in ("private/" + part.name, "/private/" + part.name)
    except OSError:
        return False


def safe_path(value):
    path = Path(value)
    if ".." in path.parts:
        raise ValueError("path traversal is not accepted")
    path = path.absolute()
    if any(part.is_symlink() and not system_alias(part) for part in (path, *path.parents)):
        raise ValueError("symlink paths are not accepted")
    return path


def reject_constant(value):
    raise ValueError(f"non-finite JSON number: {value}")


def read_layer(value):
    path = safe_path(value)
    if not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("input must be a regular JSON file of at most 4 MiB")
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError("input exceeds 4 MiB")
    try:
        data = json.loads(raw, parse_constant=reject_constant)
    except RecursionError as exc:
        raise ValueError("input JSON nesting exceeds parser capacity") from exc
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        raise ValueError("input must be a GeoJSON FeatureCollection")
    features = data.get("features")
    if not isinstance(features, list) or not 1 <= len(features) <= MAX_FEATURES:
        raise ValueError("features must be a nonempty list of at most 1000 polygons")
    count = 0
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "Feature":
            raise ValueError("each member must be a Feature")
        if "properties" not in feature or not isinstance(feature.get("properties"), (dict, type(None))):
            raise ValueError("properties must be an object or null")
        bounded_json_size(feature["properties"], MAX_OUTPUT_BYTES, level=3)
        geom = feature.get("geometry")
        if not isinstance(geom, dict) or geom.get("type") not in ("Polygon", "MultiPolygon"):
            raise ValueError("only nonempty 2D Polygon/MultiPolygon geometry is supported")
        polygons = [geom.get("coordinates")] if geom["type"] == "Polygon" else geom.get("coordinates")
        if not isinstance(polygons, list) or not polygons:
            raise ValueError("polygon coordinates must be nonempty")
        for polygon in polygons:
            if not isinstance(polygon, list) or not polygon:
                raise ValueError("polygon rings must be nonempty")
            for ring in polygon:
                if not isinstance(ring, list) or len(ring) < 4 or ring[0] != ring[-1]:
                    raise ValueError("rings must have at least four positions and be closed")
                for position in ring:
                    count += 1
                    if count > MAX_POSITIONS:
                        raise ValueError("input exceeds 100000 positions")
                    if not isinstance(position, list) or len(position) != 2:
                        raise ValueError("only 2D positions are accepted")
                    if any(type(v) not in (int, float) or not math.isfinite(v) for v in position):
                        raise ValueError("positions must contain finite numeric coordinates")
    return path, raw, data


def validate_args(args):
    for value in (args.input_crs, args.overlay_crs, args.target_crs):
        if not re.fullmatch(r"EPSG:[1-9][0-9]{0,6}", value):
            raise ValueError("CRS must be explicitly declared as EPSG:<positive integer>")
    left = read_layer(args.input)
    right = read_layer(args.overlay)
    if len(left[2]["features"]) * len(right[2]["features"]) > MAX_PAIRS:
        raise ValueError("overlay exceeds 100000 candidate feature pairs")
    output = safe_path(args.output_dir)
    if output.exists() or not output.parent.is_dir():
        raise ValueError("output directory must be new and its parent must already exist")
    return left, right, output


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value):
    limit = MAX_OUTPUT_BYTES if isinstance(value, dict) and value.get("type") == "FeatureCollection" else MAX_METADATA_BYTES
    bounded_json_size(value, limit - 1)  # reserve the final newline before allocating
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def bounded_json_size(value, limit, level=0):
    """Count indent=2/ensure_ascii JSON bytes without a whole-value serialization.

    String escaping uses at most 4096 source characters per temporary copy.
    Refuse while counting, not after allocating an expanded JSON string.
    """
    used = 0
    def charge(count):
        nonlocal used
        used += count
        if used > limit:
            raise ValueError(f"output byte budget exceeded ({limit} bytes available for this value)")
    def string_size(text):
        charge(2)
        for start in range(0, len(text), 4096):
            charge(len(json.dumps(text[start:start + 4096], ensure_ascii=True)) - 2)
    def visit(item, depth):
        if depth > MAX_JSON_DEPTH:
            raise ValueError("output JSON nesting exceeds 64 levels")
        if isinstance(item, str):
            string_size(item)
        elif isinstance(item, (dict, list, tuple)):
            if not item:
                charge(2)
                return
            charge(2)  # opening bracket and newline
            for index, key in enumerate(item):
                charge(2 * (depth + 1))
                if isinstance(item, dict):
                    string_size(key)
                    charge(2)  # colon and space
                    visit(item[key], depth + 1)
                else:
                    visit(key, depth + 1)
                charge(2 if index < len(item) - 1 else 1)  # comma/newline
            charge(2 * depth + 1)  # indentation and closing bracket
        else:
            charge(len(json.dumps(item, allow_nan=False)))
    visit(value, level)
    return used


def mercator_family(crs):
    """True for Web Mercator (EPSG:3857) and plain Mercator, whose planar areas are not ground areas."""
    operation = getattr(crs, "coordinate_operation", None)
    method = (operation.method_name if operation is not None else "").lower()
    return method.startswith("mercator") or "pseudo mercator" in method or "auxiliary sphere" in method


FIXTURE_ID = "synthetic-rectangles-v1"


def area_guard_refusal(target_is_mercator, layers):
    """Why a Mercator-family target may not measure these layers, or None when it may.

    Only the shipped synthetic fixture (both layers carry its data_class and fixture_id) is measured in
    Web Mercator; the refusal does not say how to qualify, so a real layer is never relabelled to pass.
    """
    if not target_is_mercator:
        return None
    if all(layer.get("data_class") == "synthetic" and layer.get("fixture_id") == FIXTURE_ID for layer in layers):
        return None
    return ("Web Mercator and Mercator distort area (about 1.6x at 38 degrees latitude): "
            "choose an equal-area or local projected metre CRS for the study extent")


def compute(args, left, right, shapely, pyproj):
    """Do real polygon overlay. Imports remain inside explicit invocation only."""
    from shapely.geometry import shape, mapping
    from shapely.ops import transform, unary_union
    from shapely.geometry.polygon import orient
    from shapely.errors import GEOSException
    from pyproj.exceptions import ProjError

    pyproj.network.set_network_enabled(False)
    try:
        target = pyproj.CRS(args.target_crs)
        if (not target.is_projected or len(target.axis_info) != 2
                or any(axis.unit_conversion_factor != 1.0 or axis.unit_name.lower() not in ("metre", "meter")
                       for axis in target.axis_info)):
            raise ValueError("measurement CRS must be projected with metre axes; geographic degree area/distance is refused")
        refusal = area_guard_refusal(mercator_family(target), (left[2], right[2]))
        if refusal:
            raise ValueError(refusal)
        crs_left, crs_right = pyproj.CRS(args.input_crs), pyproj.CRS(args.overlay_crs)
        def checked(geom, crs):
            if geom.is_empty or not geom.is_valid or geom.geom_type not in ("Polygon", "MultiPolygon"):
                raise ValueError("invalid or empty polygon geometry; no automatic repair")
            coords = shapely.get_coordinates(geom)
            if any(not math.isfinite(float(v)) for row in coords for v in row):
                raise ValueError("non-finite transformed coordinates")
            if crs.is_geographic:
                if any(abs(float(x)) > 180 or abs(float(y)) > 90 for x, y in coords):
                    raise ValueError("geographic coordinates outside longitude/latitude bounds")
                if geom.bounds[2] - geom.bounds[0] > 180:
                    raise ValueError("antimeridian-spanning polygons require explicit preprocessing")
            return geom
        def project_layer(layer, source):
            embedded = layer[2].get("crs")
            if embedded is not None:
                if (not isinstance(embedded, dict) or embedded.get("type") != "name"
                        or not isinstance(embedded.get("properties"), dict)
                        or "name" not in embedded["properties"]
                        or not pyproj.CRS(embedded["properties"]["name"]).equals(source)):
                    raise ValueError("embedded CRS conflicts with explicit source CRS or is unsupported")
            if not source.is_projected and not source.is_geographic:
                raise ValueError("source CRS must be a 2D geographic or projected CRS")
            if len(source.axis_info) != 2:
                raise ValueError("source CRS must have two axes")
            conversion = pyproj.Transformer.from_crs(source, target, always_xy=True, allow_ballpark=False)
            def forward(x, y, z=None):
                return conversion.transform(x, y, errcheck=True)
            return [checked(transform(forward, checked(shape(feature["geometry"]), source)), target)
                    for feature in layer[2]["features"]]
        first, second = project_layer(left, crs_left), project_layer(right, crs_right)
        to_geo = pyproj.Transformer.from_crs(target, "EPSG:4326", always_xy=True, allow_ballpark=False)
        def backward(x, y, z=None):
            return to_geo.transform(x, y, errcheck=True)
        data_class = "synthetic" if all(layer[2].get("data_class") == "synthetic" for layer in (left, right)) else "user-supplied"
        result = {"type": "FeatureCollection", "data_class": data_class, "features": []}
        features, intersections = result["features"], []
        # Count the final newline and empty collection framing once. Each pair
        # is admitted before retention; properties remain references, not copies.
        output_bytes = bounded_json_size(result, MAX_OUTPUT_BYTES - 1) + 1
        touch_only, output_positions = 0, 0
        for i, geom in enumerate(first):
            for j, other in enumerate(second):
                intersection = geom.intersection(other)
                if intersection.is_empty:
                    continue
                if intersection.area == 0:
                    touch_only += 1
                    continue
                output_positions += int(shapely.get_num_coordinates(intersection))
                if output_positions > MAX_OUTPUT_POSITIONS:
                    raise ValueError(f"output coordinate budget exceeded ({MAX_OUTPUT_POSITIONS} positions maximum)")
                checked(intersection, target)
                area, perimeter = float(intersection.area), float(intersection.length)
                if not math.isfinite(area) or not math.isfinite(perimeter):
                    raise ValueError("non-finite measured area or perimeter")
                geo = checked(transform(backward, intersection), pyproj.CRS("EPSG:4326"))
                if geo.geom_type == "Polygon":
                    geo = orient(geo, sign=1.0)
                else:
                    from shapely.geometry import MultiPolygon
                    geo = MultiPolygon([orient(part, sign=1.0) for part in geo.geoms])
                # Account for the namespaced property tree before mapping the
                # geometry or serializing any result-sized string.
                properties = {"input_index": i, "overlay_index": j, "area_m2": area, "perimeter_m": perimeter,
                    "input_properties": left[2]["features"][i]["properties"],
                    "overlay_properties": right[2]["features"][j]["properties"]}
                bounded_json_size(properties, MAX_OUTPUT_BYTES - output_bytes, level=3)
                feature = {"type": "Feature", "geometry": mapping(geo), "properties": properties}
                framing = 8 if not features else 6  # features-array indentation/separators
                output_bytes += framing + bounded_json_size(feature, MAX_OUTPUT_BYTES - output_bytes - framing, level=2)
                features.append(feature)
                intersections.append(intersection)
        summary = {"schema": "geospatial_summary/v1", "operation": "pairwise-polygon-intersection",
            "data_class": data_class, "input_feature_count": len(first), "overlay_feature_count": len(second),
            "result_feature_count": len(features), "touch_only_pair_count": touch_only,
            "measurement_crs": target.to_string(), "output_crs": "OGC:CRS84",
            "pair_area_sum_m2": math.fsum(float(g.area) for g in intersections),
            "pair_perimeter_sum_m": math.fsum(float(g.length) for g in intersections),
            "union_area_m2": float(unary_union(intersections).area) if intersections else 0.0,
            "limitations": ["Planar measurements in the declared target CRS, not geodesic ground truth; check the CRS preserves area for the study extent.",
                "Pair sums can double-count overlapping source features; union area removes duplicate coverage.",
                "Synthetic fixtures are not public-world findings. No map, raster, buffer or nearest-distance result."]}
        return result, summary
    except (GEOSException, ProjError) as exc:
        raise ValueError(f"spatial backend validation/computation failed: {exc}") from exc


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        left, right, output = validate_args(args)
        try:
            import shapely
            import pyproj
        except ImportError as exc:
            raise ValueError("optional dependencies missing; explicitly install shapely and pyproj in an isolated environment") from exc
        result, summary = compute(args, left, right, shapely, pyproj)
        bodies = {"result.geojson": json_bytes(result), "summary.json": json_bytes(summary)}
        replay = [sys.executable, str(Path(__file__).absolute()), "--input", str(left[0]),
            "--overlay", str(right[0]), "--input-crs", args.input_crs, "--overlay-crs", args.overlay_crs,
            "--target-crs", args.target_crs, "--output-dir", str(output)]
        manifest = {"schema": "geospatial_manifest/v1", "status": "observed", "data_class": summary["data_class"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "backend": {"name": "direct-shapely-pyproj", "shapely": shapely.__version__,
                "geos": shapely.geos_version_string, "pyproj": pyproj.__version__, "proj": pyproj.proj_version_str},
            "python": platform.python_version(), "platform": platform.platform(),
            "script_sha256": digest(Path(__file__).read_bytes()), "replay_argv": replay,
            "replay_note": "Choose a new --output-dir; existing directories are never overwritten.",
            "inputs": [{"path": str(layer[0]), "sha256": digest(layer[1]), "crs": crs,
                        "data_class": layer[2].get("data_class", "user-supplied")}
                       for layer, crs in ((left, args.input_crs), (right, args.overlay_crs))],
            "resource_budget": {"max_result_geojson_bytes": MAX_OUTPUT_BYTES,
                "result_geojson_bytes": len(bodies["result.geojson"]),
                "max_metadata_file_bytes": MAX_METADATA_BYTES,
                "max_result_positions": MAX_OUTPUT_POSITIONS, "max_json_depth": MAX_JSON_DEPTH,
                "policy": "fixed; reject before result retention/whole-result serialization; no truncation"},
            "outputs": {name: digest(raw) for name, raw in bodies.items()},
            "manifest_self_hash": "excluded; hash this receipt externally", "network": "disabled for PROJ"}
        manifest_raw = json_bytes(manifest)
        output.mkdir()
        for name, raw in bodies.items():
            with (output / name).open("xb") as stream:
                stream.write(raw)
        with (output / "manifest.json").open("xb") as stream:
            stream.write(manifest_raw)
        print(json.dumps({"status": "observed", "output_dir": str(output), "result_feature_count": len(result["features"])}))
        return 0
    except (ValueError, OSError, OverflowError) as exc:
        print(f"analysis refused: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
