"""Offline contracts plus separately opted-in real Shapely/PyProj QA."""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from _local_package import load_local_package
from _toolkit_path_guard import (POSIX_ONLY, assert_alias_does_not_exempt_links_below,
                                 assert_only_system_aliases_trusted)

load_local_package()
ROOT = Path(__file__).resolve().parents[1]
TOOLKIT = ROOT / "src/skills/geospatial_analysis_toolkit"
SCRIPT = TOOLKIT / "scripts/analyze.py"


def helper_api():
    spec = importlib.util.spec_from_file_location("gis_budget_helper", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def box(x0=0, y0=0, x1=10, y1=10):
    return {"type": "Feature", "properties": {}, "geometry": {"type": "Polygon",
            "coordinates": [[[x0,y0],[x1,y0],[x1,y1],[x0,y1],[x0,y0]]]}}


def layer(*features):
    return {"type": "FeatureCollection", "data_class": "synthetic", "features": list(features)}


class CliFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.left, self.right, self.output = (self.root / name for name in ("left.json", "right.json", "result"))
        self.left.write_text(json.dumps(layer(box(), box(20,0,30,10))))
        self.right.write_text(json.dumps(layer(box(5,-5,25,15))))

    def run_cli(self, *, real=False, **changes):
        values = {"input": self.left, "overlay": self.right, "input-crs": "EPSG:3857",
                  "overlay-crs": "EPSG:3857", "target-crs": "EPSG:3857", "output-dir": self.output}
        values.update(changes)
        args = [arg for key, value in values.items() if value is not None for arg in ("--" + key, str(value))]
        return subprocess.run([sys.executable, "-I", *([] if real else ["-S"]), str(SCRIPT), *args],
                              capture_output=True, text=True, timeout=30)

    def refused(self, result, message):
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn(message, result.stderr)
        self.assertNotIn('"status": "observed"', result.stdout)
        self.assertFalse(self.output.exists(), "a refused computation created output")


class GeospatialCliTests(CliFixture):
    def test_help_works_without_site_packages(self):
        result = subprocess.run([sys.executable, "-I", "-S", str(SCRIPT), "--help"],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        for flag in ("--input-crs", "--overlay-crs", "--target-crs", "--output-dir"):
            self.assertIn(flag, result.stdout)

    def test_invalid_input_fails_before_dependency_import(self):
        for invalid in ({}, layer(), layer({"type": "Feature", "geometry": None, "properties": {}})):
            with self.subTest(invalid=invalid):
                self.left.write_text(json.dumps(invalid))
                result = self.run_cli()
                self.assertEqual(result.returncode, 2)
                self.assertNotIn("dependencies missing", result.stderr)
                self.assertFalse(self.output.exists())

    def test_missing_crs_has_no_default(self):
        self.refused(self.run_cli(**{"input-crs": None}), "--input-crs")

    def test_missing_input_is_not_empty_success(self):
        self.left.unlink()
        self.refused(self.run_cli(), "regular JSON file")

    def test_nonfinite_and_boolean_coordinates_are_rejected(self):
        for value in (float("nan"), float("inf"), True, "3"):
            with self.subTest(value=value):
                data = layer(box())
                data["features"][0]["geometry"]["coordinates"][0][1][0] = value
                self.left.write_text(json.dumps(data))
                self.refused(self.run_cli(), "finite")

    def test_open_ring_and_three_dimensions_rejected(self):
        for coordinates in ([[[0,0],[10,0],[10,10],[0,10]]], [[[0,0,1],[1,0,1],[1,1,1],[0,0,1]]]):
            with self.subTest(coordinates=coordinates):
                data = layer(box())
                data["features"][0]["geometry"]["coordinates"] = coordinates
                self.left.write_text(json.dumps(data))
                result = self.run_cli()
                self.assertEqual(result.returncode, 2)
                self.assertNotIn("dependencies missing", result.stderr)
                self.assertFalse(self.output.exists())

    def test_missing_properties_rejected_as_invalid_feature(self):
        data = layer(box())
        del data["features"][0]["properties"]
        self.left.write_text(json.dumps(data))
        self.refused(self.run_cli(), "properties")

    def test_existing_output_is_preserved_before_dependencies(self):
        self.output.mkdir()
        sentinel = self.output / "manifest.json"
        sentinel.write_text("old result")
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertIn("must be new", result.stderr)
        self.assertEqual(sentinel.read_text(), "old result")
        self.assertEqual(list(self.output.iterdir()), [sentinel])

    def test_symlink_input_and_output_parent_refused(self):
        linked = self.root / "linked.json"
        linked.symlink_to(self.left)
        self.refused(self.run_cli(input=linked), "symlink")
        directory = self.root / "alias"
        directory.symlink_to(self.root, target_is_directory=True)
        self.refused(self.run_cli(**{"output-dir": directory / "result"}), "symlink")

    def test_only_macos_system_aliases_are_trusted(self):
        api = helper_api()
        assert_only_system_aliases_trusted(self, api.safe_path, api.system_alias, self.root,
                                           "symlink paths", traversal="path traversal")

    @POSIX_ONLY
    def test_a_trusted_alias_does_not_exempt_a_link_below_it(self):
        assert_alias_does_not_exempt_links_below(self, helper_api().safe_path, "symlink paths")

    def test_traversal_and_oversized_input_refused(self):
        self.refused(self.run_cli(input=self.root / ".." / "left.json"), "traversal")
        self.left.write_bytes(b" " * (4_194_304 + 1))
        self.refused(self.run_cli(), "at most 4 MiB")

    def test_candidate_pair_cap_is_checked_without_backend(self):
        self.left.write_text(json.dumps(layer(*[box() for _ in range(317)])))
        self.right.write_text(json.dumps(layer(*[box() for _ in range(317)])))
        self.refused(self.run_cli(), "100000 candidate")

    def test_excessive_input_property_nesting_refused_without_traceback(self):
        data = json.dumps(layer(box()))
        nested = '{"nested":' + '[' * 1100 + '0' + ']' * 1100 + '}'
        self.left.write_text(data.replace('"properties": {}', '"properties": ' + nested))
        result = self.run_cli()
        self.refused(result, "nesting")
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_dependencies_fail_closed(self):
        result = self.run_cli()
        self.refused(result, "dependencies missing")
        self.assertIn("shapely", result.stderr)
        self.assertIn("pyproj", result.stderr)


class GeospatialBudgetTests(unittest.TestCase):
    def test_json_size_matches_serialized_bytes_and_exact_boundary(self):
        api = helper_api()
        for value in ({}, [], None, {"nested": [{"text": "x" * 4095 + "\U0001f30d\n\"\\\x00", "null": None}, {}, []],
            "unicode_key_\U0001f30d": [True, False, 2.5, -10]}, ("a", {"b": []})):
            with self.subTest(value_type=type(value).__name__):
                expected = len(json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode("utf-8"))
                self.assertEqual(api.bounded_json_size(value, expected), expected)
                with self.assertRaisesRegex(ValueError, "output byte budget"):
                    api.bounded_json_size(value, expected - 1)


class GeospatialDefinitionTests(unittest.TestCase):
    def api(self):
        return importlib.import_module("omh.skills.geospatial_analysis_skill")

    def test_fresh_resource_factories_never_execute_companions_or_import_science(self):
        script = r'''
import builtins
from pathlib import Path
import sys
from unittest.mock import patch
root = Path(sys.argv[1])
sys.path.insert(0, str(root))
kit = root / 'src/skills/geospatial_analysis_toolkit'
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    if name.split('.')[0] in {'shapely', 'pyproj', 'geopandas', 'rasterio'}:
        raise AssertionError('science import during resource preparation')
    return original_import(name, *args, **kwargs)
def audit(event, args):
    if event == 'exec' and args and Path(args[0].co_filename).is_relative_to(kit):
        raise AssertionError('companion executed during preparation')
sys.addaudithook(audit)
with patch('builtins.__import__', side_effect=guarded_import), patch('subprocess.Popen', side_effect=AssertionError('spawn')), patch('socket.socket', side_effect=AssertionError('socket')):
    from omh.skills.geospatial_analysis_skill import geospatial_analysis_support_templates, geospatial_analysis_reference_templates
    assert geospatial_analysis_support_templates()
    assert geospatial_analysis_reference_templates()
print('inert resources: PASS')
'''
        result = subprocess.run([sys.executable, "-I", "-S", "-c", script, str(ROOT)],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("inert resources: PASS", result.stdout)

    def test_compact_body_retains_execution_pointer_without_shared_registration(self):
        from omh.skills.render import workflow_skill_from_definition
        definition = self.api().DEFINITION
        rendered = workflow_skill_from_definition(definition, definition.name).content
        self.assertIn("toolkit/README.md", rendered)
        self.assertIn("references/execution-and-qa.md", rendered)
        self.assertLess(len(rendered.encode()), 9000)

    def test_tampered_or_expanded_provenance_is_rejected(self):
        api = self.api()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            kit = root / "geospatial_analysis_toolkit"
            for name in api.TOOLKIT_RESOURCES:
                target = kit / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((TOOLKIT / name).read_bytes())
            with patch.object(api, "files", return_value=root):
                manifest_path = kit / "upstream-manifest.json"
                original = json.loads(manifest_path.read_text())
                expanded = json.loads(manifest_path.read_text())
                expanded["files"]["scripts/hidden.py"] = {"local_sha256": "0" * 64}
                manifest_path.write_text(json.dumps(expanded))
                with self.assertRaisesRegex(ValueError, "inventory"):
                    api.geospatial_analysis_support_templates()
                manifest_path.write_text(json.dumps(original))
                (kit / "scripts/analyze.py").write_text("raise RuntimeError('not executed')\n")
                with self.assertRaisesRegex(ValueError, "digest mismatch"):
                    api.geospatial_analysis_support_templates()

    def test_definition_procedure_references_and_closed_support_without_execution(self):
        api = self.api()
        with patch("subprocess.Popen", side_effect=AssertionError("hidden process")), patch("socket.socket", side_effect=AssertionError("hidden network")):
            definition = api.geospatial_analysis_definition()
            self.assertIs(definition, api.DEFINITION)
            templates = api.geospatial_analysis_support_templates()
            references = api.geospatial_analysis_reference_templates()
        self.assertEqual(definition.name, "geospatial-analysis")
        self.assertTrue(definition.progressive_disclosure)
        self.assertIn("toolkit/README.md", " ".join(definition.opening_steps))
        self.assertEqual({r.relative_path for r in references}, {"references/execution-and-qa.md"})
        self.assertEqual({t.relative_path for t in templates}, {"toolkit/" + p for p in api.TOOLKIT_RESOURCES})
        self.assertTrue(all(t.skill_name == definition.name for t in templates))
        self.assertFalse(any("geospatial_analysis_toolkit" in m for m in sys.modules))
        for step in definition.procedure_steps:
            self.assertTrue(set(step.input_refs) <= set(definition.required_inputs))
            self.assertTrue(set(step.output_refs) <= set(definition.expected_outputs))
            self.assertTrue(set(step.check_ids) <= {c.check_id for c in definition.procedure_checks})
        from omh.skills.support_files import validate_support_templates
        validate_support_templates(templates)
        contents = {t.relative_path.removeprefix("toolkit/"): t.content for t in templates}
        manifest = json.loads(contents["upstream-manifest.json"])
        self.assertEqual(set(manifest["files"]), set(api.TOOLKIT_RESOURCES) - {"upstream-manifest.json"})
        for name, entry in manifest["files"].items():
            self.assertEqual(entry["local_sha256"], hashlib.sha256(contents[name].encode()).hexdigest())
            self.assertEqual(entry["classification"], "original_omh")
            self.assertEqual(entry["upstream"], [])


class MercatorGuardTests(unittest.TestCase):
    """The area guard needs no spatial library: it reads the CRS's projection method."""

    @staticmethod
    def crs(method):
        from types import SimpleNamespace
        return SimpleNamespace(coordinate_operation=SimpleNamespace(method_name=method))

    def test_mercator_family_is_recognised_and_equal_area_or_utm_is_not(self):
        api = helper_api()
        for method in ("Popular Visualisation Pseudo Mercator", "Mercator (variant A)", "Mercator (auxiliary sphere)"):
            self.assertTrue(api.mercator_family(self.crs(method)), method)
        for method in ("Transverse Mercator", "Lambert Cylindrical Equal Area", "Albers Equal Area", "Hotine Oblique Mercator (variant B)"):
            self.assertFalse(api.mercator_family(self.crs(method)), method)
        self.assertFalse(api.mercator_family(self.crs("")))


@unittest.skipUnless(os.environ.get("OMH_GIS_RUN_REAL") == "1", "optional spatial backend")
class GeospatialRealBackendTests(CliFixture):
    def test_web_mercator_is_refused_for_user_supplied_layers_and_an_equal_area_crs_is_not(self):
        geographic = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": {
            "type": "Polygon", "coordinates": [[[126.9, 37.5], [127.0, 37.5], [127.0, 37.6], [126.9, 37.6], [126.9, 37.5]]]}}]}
        self.left.write_text(json.dumps(geographic))
        self.right.write_text(json.dumps(geographic))
        geo = {"input-crs": "EPSG:4326", "overlay-crs": "EPSG:4326"}
        self.refused(self.run_cli(real=True, **geo), "distort area")
        result = self.run_cli(real=True, **geo, **{"target-crs": "EPSG:6933"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertGreater(json.loads((self.output / "summary.json").read_text())["pair_area_sum_m2"], 0)

    def test_real_overlay_known_rectangles_and_output_hashes(self):
        result = self.run_cli(real=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads((self.output / "summary.json").read_text())
        self.assertEqual(summary["result_feature_count"], 2)
        self.assertAlmostEqual(summary["pair_area_sum_m2"], 100)
        self.assertAlmostEqual(summary["union_area_m2"], 100)
        self.assertAlmostEqual(summary["pair_perimeter_sum_m"], 60)
        self.assertEqual(summary["data_class"], "synthetic")
        output = json.loads((self.output / "result.geojson").read_text())
        self.assertEqual(len(output["features"]), 2)
        self.assertNotIn("crs", output)
        manifest = json.loads((self.output / "manifest.json").read_text())
        self.assertEqual(manifest["backend"]["name"], "direct-shapely-pyproj")
        self.assertIn("resource_budget", manifest)
        self.assertEqual(manifest["resource_budget"]["max_result_geojson_bytes"], 8_388_608)
        self.assertEqual(manifest["resource_budget"]["result_geojson_bytes"], (self.output / "result.geojson").stat().st_size)
        self.assertEqual(manifest["resource_budget"]["max_result_positions"], 100_000)
        for name, digest in manifest["outputs"].items():
            self.assertEqual(hashlib.sha256((self.output / name).read_bytes()).hexdigest(), digest)

    def test_modest_property_amplification_refused_before_result_serialization(self):
        feature = box()
        feature["properties"] = {"original_synthetic_payload": "x" * 1_048_576}
        self.left.write_text(json.dumps(layer(feature)))
        self.right.write_text(json.dumps(layer(*[box() for _ in range(32)])))
        self.refused(self.run_cli(real=True), "output byte budget")

    def compute_fixture(self, api):
        import shapely
        import pyproj
        args = api.parser().parse_args(["--input", str(self.left), "--overlay", str(self.right),
            "--input-crs", "EPSG:3857", "--overlay-crs", "EPSG:3857",
            "--target-crs", "EPSG:3857", "--output-dir", str(self.output)])
        left, right, _ = api.validate_args(args)
        return api.compute(args, left, right, shapely, pyproj)

    def test_output_position_budget_is_checked_before_geometry_mapping(self):
        api = helper_api()
        with patch.object(api, "MAX_OUTPUT_POSITIONS", 9):
            with self.assertRaisesRegex(ValueError, "output coordinate budget"):
                self.compute_fixture(api)

    def test_output_budget_exact_boundary_preserves_all_nested_properties(self):
        api = helper_api()
        properties = {"nested": [{"text": "\U0001f30d\n\"", "values": [None, False, 3]}]}
        feature = box()
        feature["properties"] = properties
        self.left.write_text(json.dumps(layer(feature)))
        result, original_summary = self.compute_fixture(api)
        size = len(api.json_bytes(result))
        with patch.object(api, "MAX_OUTPUT_BYTES", size), patch.object(api, "MAX_OUTPUT_POSITIONS", 10):
            admitted, summary = self.compute_fixture(api)
        self.assertEqual(len(api.json_bytes(admitted)), size)
        self.assertEqual(summary, original_summary)
        for item in admitted["features"]:
            self.assertEqual(item["properties"]["input_properties"], properties)
        with patch.object(api, "MAX_OUTPUT_BYTES", size - 1):
            with self.assertRaisesRegex(ValueError, "output byte budget"):
                self.compute_fixture(api)

    def test_oversized_nested_unicode_properties_refused_without_whole_result_serialization(self):
        feature = box()
        feature["properties"] = {"nested": [{"payload": "\U0001f30d" * 700_000}]}
        self.left.write_text(json.dumps(layer(feature), ensure_ascii=False), encoding="utf-8")
        self.assertLess(self.left.stat().st_size, 4_194_304)
        self.refused(self.run_cli(real=True), "output byte budget")

    def test_production_eight_mib_boundary_and_one_byte_over(self):
        api = helper_api()
        feature = box()
        feature["properties"] = {"payload": ""}
        overlays = [box() for _ in range(8)]
        overlays[0]["properties"] = {"tail": ""}
        self.left.write_text(json.dumps(layer(feature)))
        self.right.write_text(json.dumps(layer(*overlays)))
        empty, _ = self.compute_fixture(api)
        padding, remainder = divmod(api.MAX_OUTPUT_BYTES - len(api.json_bytes(empty)), 8)
        feature["properties"]["payload"] = "x" * padding
        overlays[0]["properties"]["tail"] = "x" * remainder
        self.left.write_text(json.dumps(layer(feature)))
        self.right.write_text(json.dumps(layer(*overlays)))
        result = self.run_cli(real=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.output / "result.geojson").stat().st_size, 8_388_608)
        decoded = json.loads((self.output / "result.geojson").read_bytes())
        self.assertEqual(len(decoded["features"]), 8)
        for item in decoded["features"]:
            self.assertEqual(item["properties"]["input_properties"], feature["properties"])
        self.assertEqual(decoded["features"][0]["properties"]["overlay_properties"], {"tail": "x" * remainder})
        old_manifest = (self.output / "manifest.json").read_bytes()
        old_output = self.output
        self.output = self.root / "one-byte-over"
        overlays[0]["properties"]["tail"] += "x"
        self.right.write_text(json.dumps(layer(*overlays)))
        self.refused(self.run_cli(real=True), "output byte budget")
        self.assertEqual((old_output / "manifest.json").read_bytes(), old_manifest)

    def test_oversized_manifest_metadata_refused_before_output_creation(self):
        data = json.loads(self.left.read_text())
        data["data_class"] = {"nested": "\U0001f30d" * 30_000}
        self.left.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.refused(self.run_cli(real=True, **{"target-crs": "EPSG:6933"}), "output byte budget")

    def test_geographic_degree_measurements_rejected(self):
        self.refused(self.run_cli(real=True, **{"target-crs": "EPSG:4326"}), "geographic degree")

    def test_feet_measurement_crs_rejected(self):
        self.refused(self.run_cli(real=True, **{"target-crs": "EPSG:2263"}), "metre axes")

    def test_invalid_self_intersection_is_not_repaired(self):
        data = layer(box())
        data["features"][0]["geometry"]["coordinates"] = [[[0,0],[10,10],[0,10],[10,0],[0,0]]]
        self.left.write_text(json.dumps(data))
        self.refused(self.run_cli(real=True), "invalid or empty polygon")

    def test_geographic_input_correctly_reprojects(self):
        import math
        # Independent spherical-Mercator inverse, not the helper or PyProj.
        def inverse(x, y):
            return [math.degrees(x / 6378137.0), math.degrees(2 * math.atan(math.exp(y / 6378137.0)) - math.pi / 2)]
        for path in (self.left, self.right):
            data = json.loads(path.read_text())
            for feature in data["features"]:
                feature["geometry"]["coordinates"] = [[inverse(x, y) for x, y in ring]
                                                        for ring in feature["geometry"]["coordinates"]]
            path.write_text(json.dumps(data))
        result = self.run_cli(real=True, **{"input-crs": "EPSG:4326", "overlay-crs": "EPSG:4326"})
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads((self.output / "summary.json").read_text())
        self.assertAlmostEqual(summary["union_area_m2"], 100, places=6)

    def test_conflicting_embedded_crs_refused(self):
        data = json.loads(self.left.read_text())
        data["crs"] = {"type": "name", "properties": {"name": "EPSG:4326"}}
        self.left.write_text(json.dumps(data))
        self.refused(self.run_cli(real=True), "embedded CRS conflicts")

    def test_no_intersection_is_observed_zero_not_missing_dependency(self):
        self.right.write_text(json.dumps(layer(box(100,100,110,110))))
        result = self.run_cli(real=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads((self.output / "summary.json").read_text())
        self.assertEqual(summary["result_feature_count"], 0)
        self.assertEqual(summary["union_area_m2"], 0)
        self.assertEqual(json.loads((self.output / "result.geojson").read_text())["features"], [])


if __name__ == "__main__":
    unittest.main()
