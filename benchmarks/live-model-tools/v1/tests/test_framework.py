from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "lib"))

from common import artifact_is_safe  # noqa: E402
from common import append_jsonl, tree_digest, write_json  # noqa: E402
from runner import doctor, execute_one  # noqa: E402
from statistics import analyze  # noqa: E402
from auditing import audit  # noqa: E402


class OmhBenchmarkFrameworkTests(unittest.TestCase):
    def test_doctor_reports_omh_hermes_child_contract(self) -> None:
        result = doctor(BASE, BASE / "manifest.json")
        self.assertTrue(result["ok"])
        self.assertEqual(result["capabilities"]["live_harness"], "omh_hermes_child")
        self.assertEqual(result["capabilities"]["observation_schema"], "routing_observation/v1")

    def test_fake_smoke_is_offline_and_passes(self) -> None:
        manifest = json.loads((BASE / "manifest.json").read_text())
        with TemporaryDirectory() as root:
            output = Path(root) / "runs.jsonl"
            result = execute_one(
                BASE,
                manifest,
                "development",
                "D-RENAME",
                "edit",
                7919,
                "baseline",
                output,
            )
            self.assertTrue(result["grade"]["pass"])
            self.assertEqual(result["harness"], "fake")
            self.assertTrue(artifact_is_safe(result))

    def test_artifact_gate_rejects_prompt_secret_and_absolute_path(self) -> None:
        self.assertFalse(
            artifact_is_safe(
                {
                    "schema_version": "omh_live_model_tool_run/v1",
                    "prompt": "SECRET USER PROMPT BODY",
                    "api_key": "sk-abcdefghijklmnopqrst",
                    "workspace": "/Users/victim/private/repo",
                }
            )
        )

    def test_output_symlink_and_workspace_symlinks_are_rejected(self) -> None:
        with TemporaryDirectory() as root:
            root_path = Path(root)
            target = root_path / "target.jsonl"
            target.write_text("sentinel", encoding="utf-8")
            link = root_path / "runs.jsonl"
            link.symlink_to(target)
            with self.assertRaises(OSError):
                append_jsonl(link, {"safe": True})
            with self.assertRaises(OSError):
                write_json(link, {"safe": True})
            self.assertEqual(target.read_text(encoding="utf-8"), "sentinel")
            outside = root_path / "outside.txt"
            outside.write_text("private", encoding="utf-8")
            workspace = root_path / "workspace"
            workspace.mkdir()
            (workspace / "escape").symlink_to(outside)
            with self.assertRaisesRegex(ValueError, "symlink"):
                tree_digest(workspace)

    def test_live_harness_is_blocked_without_explicit_flag(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(BASE / "bench.py"), "smoke", "--harness", "omh"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("requires --allow-paid-live", completed.stderr)

    def test_live_harness_requires_explicit_call_budget(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                str(BASE / "bench.py"),
                "smoke",
                "--harness",
                "omh",
                "--allow-paid-live",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("requires --max-paid-calls", completed.stderr)

    def test_offline_receipt_counts_zero_paid_calls(self) -> None:
        manifest = json.loads((BASE / "manifest.json").read_text())
        with TemporaryDirectory() as root:
            from runner import run_matrix

            receipt = run_matrix(
                BASE,
                manifest,
                "development",
                "baseline",
                Path(root) / "runs.jsonl",
            )
            self.assertEqual(receipt["paid_calls_launched"], 0)
            self.assertIs(type(receipt["paid_calls_launched"]), int)

    def test_help_names_omh_and_never_omo(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(BASE / "bench.py"), "--help"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn("OMH-native Hermes Agent", completed.stdout)
        self.assertNotIn("OMO", completed.stdout)

    def test_run_record_schema_matches_observation_summary(self) -> None:
        schema = json.loads((BASE / "schemas" / "run-record.schema.json").read_text())
        self.assertEqual(schema["$id"], "omh_live_model_tool_run/v1")
        self.assertEqual(
            set(schema["properties"]["observation"]["required"]),
            {"status", "tools", "tokens", "cost_usd"},
        )
        answer_schema = json.loads((BASE / "schemas" / "final-answer.schema.json").read_text())
        self.assertEqual(answer_schema["$id"], "omh_live_model_tool_answer/v1")
        self.assertTrue(answer_schema["additionalProperties"])

    def test_analysis_compares_equal_task_digests(self) -> None:
        manifest = json.loads((BASE / "manifest.json").read_text())
        with TemporaryDirectory() as root:
            root_path = Path(root)
            baseline = root_path / "baseline.jsonl"
            optimized = root_path / "optimized.jsonl"
            for condition, output in (("baseline", baseline), ("optimized", optimized)):
                execute_one(
                    BASE,
                    manifest,
                    "development",
                    "D-RENAME",
                    "edit",
                    7919,
                    condition,
                    output,
                )
            result = analyze(baseline, optimized, 100, 7, manifest)
            self.assertEqual(result["models"]["offline/fake-model"]["n"], 1)
            self.assertEqual(result["models"]["offline/fake-model"]["delta"], 0)
            report = root_path / "analysis.json"
            write_json(report, result)
            audited = audit(BASE / "manifest.json", report)
            self.assertTrue(audited["ok"])
            self.assertFalse(audited["claim_permitted"])

    def test_analysis_rejects_unscheduled_model_claim_matrix(self) -> None:
        manifest = json.loads((BASE / "manifest.json").read_text())
        with TemporaryDirectory() as root:
            root_path = Path(root)
            baseline = root_path / "baseline.jsonl"
            optimized = root_path / "optimized.jsonl"
            row = {
                "schema_version": "omh_live_model_tool_run/v1",
                "created_at": "2026-08-13T00:00:00+00:00",
                "instance_id": "fabricated-1",
                "split": "development",
                "harness": "omh",
                "model": {"provider": "not-in-manifest", "id": "fabricated-model"},
                "task_digest": "0" * 64,
                "route": {},
                "observation": {
                    "status": "completed",
                    "tools": 1,
                    "tokens": 1,
                    "cost_usd": 0.0,
                },
                "grade": {"pass": True},
                "final_tree_digest": "1" * 64,
            }
            for condition, path in (("baseline", baseline), ("optimized", optimized)):
                current = {**row, "condition": condition}
                path.write_text(json.dumps(current) + "\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "live manifest matrix"):
                analyze(baseline, optimized, 10, 7, manifest)

    def test_analysis_rejects_optimized_development_split(self) -> None:
        manifest = json.loads((BASE / "manifest.json").read_text())
        records = {}
        for model in manifest["models"]:
            if not model.get("live"):
                continue
            for template, _task_class in __import__("corpus").TEMPLATES:
                for seed in __import__("corpus").EVALUATION_SEEDS:
                    instance_id = f"E-{template}-{seed}"
                    records[(model["provider"], model["id"], instance_id)] = {
                        "schema_version": "omh_live_model_tool_run/v1",
                        "created_at": "2026-08-13T00:00:00+00:00",
                        "instance_id": instance_id,
                        "split": "evaluation",
                        "harness": "omh",
                        "model": model,
                        "task_digest": "0" * 64,
                        "route": {},
                        "observation": {
                            "status": "completed",
                            "tools": 1,
                            "tokens": 1,
                            "cost_usd": 0.0,
                        },
                        "grade": {"pass": True},
                        "final_tree_digest": "1" * 64,
                    }
        with TemporaryDirectory() as root:
            root_path = Path(root)
            baseline = root_path / "baseline.jsonl"
            optimized = root_path / "optimized.jsonl"
            baseline.write_text(
                "".join(
                    json.dumps({**row, "condition": "baseline"}) + "\n"
                    for row in records.values()
                ),
                encoding="utf-8",
            )
            optimized.write_text(
                "".join(
                    json.dumps(
                        {**row, "condition": "optimized", "split": "development"}
                    )
                    + "\n"
                    for row in records.values()
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "evaluation split"):
                analyze(baseline, optimized, 10, 7, manifest)


class OmhTargetedManifestAnalysisTests(unittest.TestCase):
    """Issue #1056 step-0: targeted family manifests must flow end-to-end.

    bench.py run accepts --manifest, but the analyze.py CLI used to reload the
    canonical manifest directly, so a targeted manifest (for example, one live
    solar family entry) could run but never pass the analysis coverage check.
    These tests pin the CLI contract: --manifest selects the manifest used for
    analysis coverage, defaults stay canonical, and mismatched manifests still
    fail loudly.
    """

    def _run_cli(self, args):
        return subprocess.run(
            [sys.executable, str(BASE / "analyze.py"), *args],
            capture_output=True,
            text=True,
        )

    def _live_manifest(self):
        manifest = json.loads((BASE / "manifest.json").read_text())
        manifest["models"] = [m for m in manifest["models"] if m.get("live")][:1]
        return manifest

    def _evaluation_rows(self, manifest, condition):
        import corpus

        model = next(m for m in manifest["models"] if m.get("live"))
        rows = []
        for template, _task_class in corpus.TEMPLATES:
            for seed in corpus.EVALUATION_SEEDS:
                rows.append(
                    {
                        "schema_version": "omh_live_model_tool_run/v1",
                        "created_at": "2026-08-13T00:00:00+00:00",
                        "instance_id": f"E-{template}-{seed}",
                        "split": "evaluation",
                        "harness": "omh",
                        "model": {"provider": model["provider"], "id": model["id"]},
                        "task_digest": "a" * 64,
                        "route": {},
                        "observation": {
                            "status": "completed",
                            "tools": 1,
                            "tokens": 1,
                            "cost_usd": 0.0,
                        },
                        "grade": {"pass": True},
                        "final_tree_digest": "b" * 64,
                        "condition": condition,
                    }
                )
        return rows

    def test_targeted_manifest_cli_analyze_end_to_end(self) -> None:
        manifest = self._live_manifest()
        with TemporaryDirectory() as root:
            root_path = Path(root)
            manifest_path = root_path / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            baseline = root_path / "baseline.jsonl"
            optimized = root_path / "optimized.jsonl"
            for condition, output in (("baseline", baseline), ("optimized", optimized)):
                rows = self._evaluation_rows(manifest, condition)
                output.write_text(
                    "".join(json.dumps(row) + chr(10) for row in rows),
                    encoding="utf-8",
                )
            result = self._run_cli(
                [
                    "--baseline", str(baseline),
                    "--optimized", str(optimized),
                    "--manifest", str(manifest_path),
                    "--bootstrap-repetitions", "100",
                    "--seed", "7",
                    "--output", str(root_path / "report.json"),
                ]
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((root_path / "report.json").read_text())
            model = next(m for m in manifest["models"] if m.get("live"))
            label = f"{model['provider']}/{model['id']}"
            self.assertIn(label, report["models"])
            self.assertEqual(
                report["models"][label]["n"],
                len(self._evaluation_rows(manifest, "baseline")),
            )

    def test_targeted_manifest_cli_rejects_mismatched_manifest(self) -> None:
        manifest = self._live_manifest()
        excluded = manifest["models"][0]
        other = self._live_manifest()
        other["models"] = [
            m
            for m in other["models"]
            if (m["provider"], m["id"]) != (excluded["provider"], excluded["id"])
        ]
        with TemporaryDirectory() as root:
            root_path = Path(root)
            other_path = root_path / "other.json"
            other_path.write_text(json.dumps(other), encoding="utf-8")
            baseline = root_path / "baseline.jsonl"
            baseline.write_text(
                "".join(
                    json.dumps(row) + chr(10)
                    for row in self._evaluation_rows(manifest, "baseline")
                ),
                encoding="utf-8",
            )
            result = self._run_cli(
                [
                    "--baseline", str(baseline),
                    "--optimized", str(baseline),
                    "--manifest", str(other_path),
                    "--bootstrap-repetitions", "100",
                    "--output", str(root_path / "report.json"),
                ]
            )
            self.assertNotEqual(result.returncode, 0)

    def test_cli_analyze_defaults_to_canonical_manifest(self) -> None:
        manifest = self._live_manifest()
        with TemporaryDirectory() as root:
            root_path = Path(root)
            baseline = root_path / "baseline.jsonl"
            baseline.write_text(
                "".join(
                    json.dumps(row) + chr(10)
                    for row in self._evaluation_rows(manifest, "baseline")
                ),
                encoding="utf-8",
            )
            result = self._run_cli(
                [
                    "--baseline", str(baseline),
                    "--optimized", str(baseline),
                    "--bootstrap-repetitions", "100",
                    "--output", str(root_path / "report.json"),
                ]
            )
            # One targeted live model against the canonical manifest violates
            # the canonical matrix check: the old failure mode, still intact.
            self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()

