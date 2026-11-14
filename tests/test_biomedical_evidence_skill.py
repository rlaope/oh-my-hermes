"""Original synthetic schema fixtures; never live biomedical findings."""
from __future__ import annotations

import contextlib
import hashlib
import importlib
import io
import json
import subprocess
import sys
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch

import _local_package  # noqa: F401
from _toolkit_path_guard import (POSIX_ONLY, assert_alias_does_not_exempt_links_below,
                                 assert_only_system_aliases_trusted, assert_unsearchable_directory_is_refused)

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "src/skills/biomedical_evidence_toolkit/scripts/reconcile.py"


class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.api = runpy.run_path(str(SCRIPT))
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def fixture(self, *, gene="TESTGENE", classification="fixture-class-a"):
        variant = {
            "gene": gene, "id": "fixture-coordinate", "legacy_name": "TESTGENE TESTCHANGE",
            "genome_build": "fixture-build", "transcript": "fixture-transcript",
            "hgvs_c": "fixture-c", "hgvs_p": "fixture-p",
            "_meta": {"section_sources": [{"key": "clinvar", "outcome": "data", "sources": ["NCBI ClinVar"]}]},
            "section_outcomes": {"clinvar": {"outcome": "data", "sources": ["NCBI ClinVar"]}},
            "clinvar": {
                "accession": "VCV_TEST", "source": "NCBI ClinVar",
                "germline_classification": {"classification": classification, "evaluation_date": "2026-10-01"},
                "aggregates": [{"accession": "RCV_TEST", "classification": classification,
                                "classification_domain": "germline", "conditions": ["Fixture disease"],
                                "evaluation_date": "2026-10-01"}],
                "submissions": [],
            },
        }
        trial = {"nct_id": "NCT00000000", "source": "ClinicalTrials.gov", "title": "Fixture registry record",
                 "status": "FIXTURE_STATUS", "conditions": ["Fixture disease"], "last_update_posted": "2026-10-01",
                 "_meta": {"section_sources": [{"key": "overview", "outcome": "data", "sources": ["ClinicalTrials.gov"]}]}}
        captures = []
        for label, source, payload in [("cv", "ClinVar", variant), ("ct", "ClinicalTrials.gov", trial)]:
            out, err = label + ".json", label + ".stderr"
            data = (json.dumps(payload) + "\n").encode()
            (self.root / out).write_bytes(data)
            (self.root / err).write_bytes(b"")
            captures.append({"source": source, "argv": ["biomcp", "--json", "get", "fixture", label],
                             "version": "biomcp 0.9.3", "started_at": "2026-10-22T00:00:00+00:00",
                             "finished_at": "2026-10-22T00:00:01+00:00", "exit_code": 0,
                             "stdout_path": out, "stderr_path": err, "sha256": hashlib.sha256(data).hexdigest(),
                             "stderr_sha256": hashlib.sha256(b"").hexdigest()})
        manifest = {"schema": "biomedical_captures/v1", "data_class": "synthetic_schema_fixture",
                    "query": {"gene": "TESTGENE", "variant": "TESTGENE TESTCHANGE", "disease": "Fixture disease"},
                    "captures": captures}
        return manifest

    def reconcile(self, manifest):
        path = self.root / "captures.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        return self.api["reconcile"](path)

    def test_matching_public_entity_schema_retains_query_raw_hash_and_context(self):
        manifest = self.fixture()
        result = self.reconcile(manifest)
        self.assertEqual(result["availability"], "complete")
        self.assertEqual(result["status"], "complete")
        self.assertEqual(result["query"], manifest["query"])
        self.assertEqual(result["sources"][0]["identity"]["genome_build"], "fixture-build")
        self.assertEqual(result["sources"][0]["receipt"]["sha256"], manifest["captures"][0]["sha256"])
        self.assertEqual(result["sources"][0]["claims"][0]["assertion"]["classification"], "fixture-class-a")
        self.assertEqual(result["sources"][1]["variant_relationship"], "not_established")

    def replace_payload(self, manifest, index, payload):
        data = (json.dumps(payload) + "\n").encode()
        receipt = manifest["captures"][index]
        (self.root / receipt["stdout_path"]).write_bytes(data)
        receipt["sha256"] = hashlib.sha256(data).hexdigest()

    def test_failed_missing_embedded_and_unknown_schema_sources_are_not_empty_success(self):
        for failure in ("exit", "embedded", "missing", "schema", "invalid_json", "metadata", "trial_embedded"):
            with self.subTest(failure=failure):
                manifest = self.fixture()
                if failure == "exit":
                    manifest["captures"][1]["exit_code"] = 124
                elif failure == "missing":
                    manifest["captures"].pop()
                elif failure == "embedded":
                    payload = json.loads((self.root / "cv.json").read_text())
                    payload["section_outcomes"]["clinvar"] = {"outcome": "error", "error": "fixture timeout"}
                    self.replace_payload(manifest, 0, payload)
                elif failure == "trial_embedded":
                    payload = json.loads((self.root / "ct.json").read_text())
                    payload["_meta"]["section_sources"].append({"key": "conditions", "outcome": "error", "sources": ["ClinicalTrials.gov"]})
                    self.replace_payload(manifest, 1, payload)
                elif failure == "schema":
                    self.replace_payload(manifest, 1, {"unexpected": []})
                elif failure == "metadata":
                    payload = json.loads((self.root / "cv.json").read_text())
                    payload.pop("_meta")
                    self.replace_payload(manifest, 0, payload)
                else:
                    (self.root / "ct.json").write_bytes(b"not-json")
                    manifest["captures"][1]["sha256"] = hashlib.sha256(b"not-json").hexdigest()
                result = self.reconcile(manifest)
                self.assertEqual(result["availability"], "partial")
                self.assertEqual(result["status"], "partial")
                self.assertEqual(len(result["sources"]), 2)
                self.assertTrue(any(s["status"] != "available" for s in result["sources"]))

    def test_every_assertion_requires_nonblank_string_classification(self):
        # Schema labels are synthetic, not a clinical classification vocabulary.
        cases = {"absent": None, "null": None, "empty": "", "blank": " \t\n",
                 "object": {"error": "fixture-schema-change"}, "list": ["fixture-class-a"],
                 "true": True, "false": False, "number": 1}
        for scope in ("germline_classification", "aggregates", "submissions"):
            for kind, value in cases.items():
                with self.subTest(scope=scope, kind=kind):
                    manifest = self.fixture()
                    payload = json.loads((self.root / "cv.json").read_text())
                    cv = payload["clinvar"]
                    if scope == "germline_classification":
                        assertion = cv[scope]
                        pointer = "/clinvar/" + scope
                    else:
                        # A valid earlier row must not conceal a malformed later one.
                        cv[scope] = [dict(cv["aggregates"][0]), dict(cv["aggregates"][0])]
                        assertion = cv[scope][1]
                        pointer = f"/clinvar/{scope}/1"
                    if kind == "absent":
                        assertion.pop("classification")
                    else:
                        assertion["classification"] = value
                    self.replace_payload(manifest, 0, payload)
                    raw_before = (self.root / "cv.json").read_bytes()
                    capture = self.root / "captures.json"
                    capture.write_text(json.dumps(manifest), encoding="utf-8")
                    output = self.root / (scope + "-" + kind)
                    with contextlib.redirect_stdout(io.StringIO()):
                        code = self.api["main"](["--capture-manifest", str(capture), "--output-dir", str(output)])
                    self.assertEqual(code, 3)
                    result = json.loads((output / "evidence-matrix.json").read_text())
                    self.assertEqual(result["status"], "partial")
                    self.assertEqual(result["availability"], "partial")
                    row = result["sources"][0]
                    self.assertEqual(row["status"], "unavailable")
                    self.assertIn("clinvar_assertion_schema_mismatch:" + pointer, row["gaps"])
                    claim = next(c for c in row["claims"] if c["path"] == pointer)
                    self.assertEqual(claim["assertion"], assertion)
                    self.assertEqual(claim["status"], "unavailable")
                    self.assertEqual(claim["failure"], "clinvar_assertion_schema_mismatch")
                    self.assertFalse(any(d.get("path") == pointer or pointer in d.get("paths", [])
                                         for d in row["disagreements"]))
                    self.assertEqual(result["sources"][1]["status"], "available")
                    self.assertEqual((self.root / "cv.json").read_bytes(), raw_before)
                    receipt = json.loads((output / "manifest.json").read_text())
                    self.assertEqual(receipt["status"], "partial")
                    self.assertEqual(receipt["outputs"]["evidence-matrix.json"],
                                     hashlib.sha256((output / "evidence-matrix.json").read_bytes()).hexdigest())

    def test_contradictory_assertions_are_retained_only_within_same_context(self):
        manifest = self.fixture()
        payload = json.loads((self.root / "cv.json").read_text())
        first = payload["clinvar"]["aggregates"][0]
        payload["clinvar"]["submissions"] = [dict(first, accession="SCV_FIXTURE_1", submitter="Fixture A"),
                                                dict(first, accession="SCV_FIXTURE_2", classification="fixture-class-b", submitter="Fixture B"),
                                                dict(first, accession="SCV_FIXTURE_3", classification="fixture-class-c", classification_domain="somatic clinical impact")]
        payload["significance_note"] = "Fixture cached versus primary disagreement; not a biological finding."
        self.replace_payload(manifest, 0, payload)
        result = self.reconcile(manifest)
        row = result["sources"][0]
        differences = [d for d in row["disagreements"] if d["kind"] == "differing_assertions_same_context"]
        self.assertEqual(len(differences), 1)
        self.assertEqual(set(differences[0]["values"]), {"fixture-class-a", "fixture-class-b"})
        self.assertEqual(len(row["claims"]), 5)
        self.assertTrue(any(d["kind"] == "upstream_significance_note" for d in row["disagreements"]))
        self.assertNotIn("consensus", row)

    def test_missing_and_old_source_times_never_become_retrieval_times(self):
        manifest = self.fixture()
        cv = json.loads((self.root / "cv.json").read_text())
        cv["clinvar"]["germline_classification"].pop("evaluation_date")
        cv["clinvar"]["aggregates"][0]["evaluation_date"] = "2010-01-01"
        self.replace_payload(manifest, 0, cv)
        ct = json.loads((self.root / "ct.json").read_text())
        ct.pop("last_update_posted")
        self.replace_payload(manifest, 1, ct)
        result = self.reconcile(manifest)
        self.assertEqual(result["status"], "partial")
        missing = result["sources"][0]["claims"][0]["freshness"]
        self.assertIsNone(missing["source_time"])
        self.assertEqual(missing["status"], "unknown")
        old = result["sources"][0]["claims"][1]["freshness"]
        self.assertGreater(old["age_days"], 365)
        self.assertEqual(old["time_kind"], "evaluation_date_not_update")
        self.assertIsNone(result["sources"][1]["freshness"]["source_time"])
        self.assertIn("source_update_time_absent", result["sources"][1]["gaps"])

    def test_literal_intended_ids_and_disease_mismatches_do_not_silently_normalize(self):
        for intended in ({"genome_build": "DIFFERENT_BUILD"}, {"transcript": " fixture-transcript"},
                         {"accession": "OTHER_ACCESSION"}, {"nct_id": "NCT00000001"}):
            with self.subTest(intended=intended):
                manifest = self.fixture()
                manifest["intended_ids"] = intended
                result = self.reconcile(manifest)
                self.assertEqual(result["status"], "partial")
                self.assertEqual(result["intended_ids"], intended)
        manifest = self.fixture()
        manifest["query"]["disease"] = "Another fixture disease"
        result = self.reconcile(manifest)
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["sources"][1]["disease_matching_basis"], "not_established")

    def test_cli_emits_hashed_matrix_and_partial_exit_without_mutating_raw(self):
        manifest = self.fixture()
        manifest["captures"][1]["exit_code"] = 1
        path = self.root / "captures.json"
        path.write_text(json.dumps(manifest), encoding="utf-8")
        raw_before = (self.root / "cv.json").read_bytes()
        output = self.root / "output"
        with contextlib.redirect_stdout(io.StringIO()):
            code = self.api["main"](["--capture-manifest", str(path), "--output-dir", str(output)])
        self.assertEqual(code, 3)
        matrix = json.loads((output / "evidence-matrix.json").read_text())
        receipt = json.loads((output / "manifest.json").read_text())
        self.assertEqual(matrix["status"], "partial")
        self.assertEqual(receipt["outputs"]["evidence-matrix.json"], hashlib.sha256((output / "evidence-matrix.json").read_bytes()).hexdigest())
        self.assertEqual((self.root / "cv.json").read_bytes(), raw_before)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.api["main"](["--capture-manifest", str(path), "--output-dir", str(output)]), 2)
        self.assertEqual(json.loads((output / "manifest.json").read_text()), receipt)

    def test_hash_traversal_and_symlink_tampering_are_refused(self):
        for kind in ("digest", "stderr_digest", "traversal", "absolute", "symlink", "naive_time"):
            with self.subTest(kind=kind):
                manifest = self.fixture()
                capture = manifest["captures"][0]
                if kind == "digest":
                    capture["sha256"] = "0" * 64
                elif kind == "stderr_digest":
                    capture["stderr_sha256"] = "0" * 64
                elif kind == "traversal":
                    capture["stdout_path"] = "../cv.json"
                elif kind == "absolute":
                    capture["stdout_path"] = str(self.root / "cv.json")
                elif kind == "symlink":
                    link = self.root / "link.json"
                    link.symlink_to(self.root / "cv.json")
                    capture["stdout_path"] = "link.json"
                else:
                    capture["finished_at"] = "2026-10-22T00:00:01"
                with self.assertRaises(ValueError):
                    self.reconcile(manifest)

    def test_only_macos_system_aliases_are_trusted(self):
        assert_only_system_aliases_trusted(self, self.api["safe_path"], self.api["system_alias"], self.root,
                                           "symlinks and traversal", traversal="symlinks and traversal")

    @POSIX_ONLY
    def test_a_trusted_alias_does_not_exempt_a_link_below_it(self):
        assert_alias_does_not_exempt_links_below(self, self.api["safe_path"], "symlinks and traversal")

    def test_an_unsearchable_directory_is_refused(self):
        assert_unsearchable_directory_is_refused(self, self.api["safe_path"], self.root)

    def test_help_is_dependency_free(self):
        result = subprocess.run([sys.executable, "-I", str(SCRIPT), "--help"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--capture-manifest", result.stdout)

    def test_nonpublic_scope_and_malformed_assertion_shapes_are_not_accepted(self):
        manifest = self.fixture()
        manifest["data_class"] = "patient_record"
        with self.assertRaises(ValueError):
            self.reconcile(manifest)
        for payload in (["unexpected"], {"error": "fixture API denial"}, {"clinvar": {}},
                        {"nct_id": "bad-id", "status": "FIXTURE", "conditions": ["Fixture disease"],
                         "_meta": {"section_sources": [{"key": "overview", "outcome": "data", "sources": ["ClinicalTrials.gov"]}]}}):
            with self.subTest(payload=payload):
                manifest = self.fixture()
                self.replace_payload(manifest, 1, payload)
                self.assertEqual(self.reconcile(manifest)["availability"], "partial")
        manifest = self.fixture()
        cv = json.loads((self.root / "cv.json").read_text())
        cv["clinvar"]["germline_classification"] = {}
        cv["clinvar"]["aggregates"] = []
        self.replace_payload(manifest, 0, cv)
        self.assertEqual(self.reconcile(manifest)["availability"], "partial")

    def test_identity_mismatch_is_partial_and_cannot_be_merged(self):
        result = self.reconcile(self.fixture(gene="OTHER_FIXTURE_GENE"))
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["sources"][0]["identity_status"], "mismatch")
        self.assertIn("gene_mismatch", result["sources"][0]["gaps"])


class DefinitionTests(unittest.TestCase):
    def test_provenance_cannot_expand_inventory_or_accept_changed_bytes(self):
        module = importlib.import_module("omh.skills.biomedical_evidence_skill")
        canonical = ROOT / "src/skills/biomedical_evidence_toolkit"
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            target = base / "biomedical_evidence_toolkit"
            target.mkdir()
            for relative in module.TOOLKIT_RESOURCES:
                destination = target / relative
                destination.parent.mkdir(exist_ok=True)
                destination.write_bytes((canonical / relative).read_bytes())
            with patch.object(module, "files", return_value=base):
                self.assertEqual(len(module.biomedical_evidence_support_templates()), len(module.TOOLKIT_RESOURCES))
                (target / "README.md").write_text("changed fixture bytes", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "hash mismatch"):
                    module.biomedical_evidence_support_templates()
                (target / "README.md").write_bytes((canonical / "README.md").read_bytes())
                provenance = json.loads((target / "upstream-manifest.json").read_text())
                provenance["files"]["unreviewed.py"] = {"local_sha256": "0" * 64}
                (target / "upstream-manifest.json").write_text(json.dumps(provenance), encoding="utf-8")
                with self.assertRaisesRegex(ValueError, "inventory"):
                    module.biomedical_evidence_support_templates()

    def test_closed_factories_preserve_resource_hashes_without_importing_helper(self):
        module = importlib.import_module("omh.skills.biomedical_evidence_skill")
        self.assertIs(module.biomedical_evidence_definition(), module.DEFINITION)
        self.assertTrue(module.DEFINITION.progressive_disclosure)
        self.assertEqual(module.DEFINITION.reasoning_demand, "heavy")
        self.assertGreaterEqual(len(module.DEFINITION.situations), 5)
        templates = module.biomedical_evidence_support_templates()
        self.assertEqual({t.relative_path for t in templates}, {"toolkit/" + p for p in module.TOOLKIT_RESOURCES})
        manifest = module.biomedical_evidence_provenance_manifest()
        self.assertEqual(set(manifest["files"]), set(module.TOOLKIT_RESOURCES) - {"upstream-manifest.json"})
        for template in templates:
            if template.relative_path != "toolkit/upstream-manifest.json":
                item = manifest["files"][template.relative_path.removeprefix("toolkit/")]
                self.assertEqual(item["local_sha256"], hashlib.sha256(template.content.encode()).hexdigest())
                self.assertEqual(item["classification"], "original_omh")
        refs = module.biomedical_evidence_reference_templates()
        self.assertTrue(any(t.relative_path == "references/execution-and-qa.md" for t in refs))
        self.assertFalse(any("biomedical_evidence_toolkit.scripts" in name for name in sys.modules))
        inputs, outputs = set(module.DEFINITION.required_inputs), set(module.DEFINITION.expected_outputs)
        checks = {c.check_id for c in module.DEFINITION.procedure_checks}
        for step in module.DEFINITION.procedure_steps:
            self.assertTrue(set(step.input_refs) <= inputs)
            self.assertTrue(set(step.output_refs) <= outputs)
            self.assertTrue(set(step.check_ids) <= checks)


if __name__ == "__main__":
    unittest.main()
