"""Contract and execution tests for the 3 offline stdlib companion toolkits."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from omh.skills.support_files import (
    agent_skill_support_templates,
    builtin_skill_support_templates,
    builtin_support_owners,
)
from omh.skills.value_mechanisms import (
    VALUE_MECHANISM_EXECUTABLE_TOOLKIT,
    value_mechanisms_for_skill,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RESIDUAL_SCAN = REPO_ROOT / "src/skills/data_share_review_toolkit/scripts/residual_scan.py"
MERGE_DANGER_SCAN = REPO_ROOT / "src/skills/commit_pr_authoring_toolkit/scripts/merge_danger_scan.py"
VRAM_KV_CALC = REPO_ROOT / "src/skills/inference_serving_toolkit/scripts/vram_kv_calc.py"


class OfflineSkillToolkitsTests(unittest.TestCase):
    def test_all_three_toolkits_registered_in_builtin_and_portable_inventories(self) -> None:
        owners = builtin_support_owners()
        for skill in ("data-share-review", "commit-pr-authoring", "inference-serving"):
            self.assertIn(skill, owners)
            self.assertIn(VALUE_MECHANISM_EXECUTABLE_TOOLKIT, value_mechanisms_for_skill(skill))

        builtin_keys = {(t.skill_name, t.relative_path) for t in builtin_skill_support_templates()}
        portable_keys = {(t.skill_name, t.relative_path) for t in agent_skill_support_templates()}
        expected_pairs = (
            ("data-share-review", "omh-data-share-review", "toolkit/scripts/residual_scan.py"),
            ("commit-pr-authoring", "omh-commit-pr-authoring", "toolkit/scripts/merge_danger_scan.py"),
            ("inference-serving", "omh-inference-serving", "toolkit/scripts/vram_kv_calc.py"),
        )
        for canonical, label, rel in expected_pairs:
            self.assertIn((canonical, rel), builtin_keys)
            self.assertIn((label, rel), portable_keys)

    def test_residual_scan_detects_pii_and_secrets_without_echoing_values(self) -> None:
        secret_email = "alice.secret@example.org"
        secret_key = "sk-proj-TestValueNeverEcho1234567890"
        secret_path = "/Users/demo/Desktop/export.csv"
        with TemporaryDirectory() as tmp:
            dirty = Path(tmp) / "tickets.csv"
            dirty.write_text(
                "id,notes\n"
                f"1,Contact {secret_email} or call 010-1234-5678\n"
                f"2,Leak {secret_key} from {secret_path} and 900101-1234567\n",
                encoding="utf-8",
            )
            proc = subprocess.run(
                [sys.executable, str(RESIDUAL_SCAN), "--input", str(dirty), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 1, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["schema_version"], "residual_scan/v1")
            self.assertEqual(payload["verdict"], "not_redacted")
            self.assertGreaterEqual(payload["counts_by_class"]["email"], 1)
            self.assertGreaterEqual(payload["counts_by_class"]["phone"], 1)
            self.assertGreaterEqual(payload["counts_by_class"]["national_id"], 1)
            self.assertGreaterEqual(payload["counts_by_class"]["vendor_secret"], 1)
            self.assertGreaterEqual(payload["counts_by_class"]["absolute_local_path"], 1)
            self.assertIn("notes", payload["fields_with_hits"])
            # Critical safety rule: never echo any matched value in stdout or stderr.
            combined = proc.stdout + proc.stderr
            self.assertNotIn(secret_email, combined)
            self.assertNotIn(secret_key, combined)
            self.assertNotIn(secret_path, combined)

            clean = Path(tmp) / "clean.csv"
            clean.write_text("id,region,count\n1,KR,42\n2,US,19\n", encoding="utf-8")
            proc_unsampled = subprocess.run(
                [sys.executable, str(RESIDUAL_SCAN), "--input", str(clean), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc_unsampled.returncode, 0)
            self.assertEqual(json.loads(proc_unsampled.stdout)["verdict"], "needs_free_text_sample")

            proc_sampled = subprocess.run(
                [sys.executable, str(RESIDUAL_SCAN), "--input", str(clean), "--free-text-sampled", "--json"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc_sampled.returncode, 0)
            self.assertEqual(json.loads(proc_sampled.stdout)["verdict"], "redacted")

    def test_merge_danger_scan_flags_hazards_and_suppresses_secret_values(self) -> None:
        leaked = "ghp_ExampleTokenNeverEcho1234567890abcd"
        diff = "\n".join(
            [
                "diff --git a/db/migrations/0042_users.sql b/db/migrations/0042_users.sql",
                "--- a/db/migrations/0042_users.sql",
                "+++ b/db/migrations/0042_users.sql",
                "@@ -0,0 +1,2 @@",
                "+ALTER TABLE users ADD COLUMN role TEXT;",
                "diff --git a/pyproject.toml b/pyproject.toml",
                "--- a/pyproject.toml",
                "+++ b/pyproject.toml",
                "@@ -1,1 +1,1 @@",
                "-dependencies = []",
                '+dependencies = ["requests"]',
                "diff --git a/src/api.py b/src/api.py",
                "--- a/src/api.py",
                "+++ b/src/api.py",
                "@@ -1,2 +1,2 @@",
                "-def public_handler(req):",
                f'+TOKEN = "{leaked}"',
            ]
        )
        with TemporaryDirectory() as tmp:
            patch_path = Path(tmp) / "change.patch"
            patch_path.write_text(diff, encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, str(MERGE_DANGER_SCAN), "--diff-file", str(patch_path), "--json"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(proc.returncode, 1, proc.stderr)
            payload = json.loads(proc.stdout)
            self.assertEqual(payload["schema_version"], "merge_danger_scan/v1")
            self.assertEqual(payload["risk_level"], "critical")
            categories = {item["category"] for item in payload["findings"]}
            self.assertTrue(
                {
                    "schema_or_migration",
                    "dependency_or_lockfile",
                    "public_symbol_removed",
                    "possible_secret_added",
                }.issubset(categories)
            )
            self.assertNotIn(leaked, proc.stdout + proc.stderr)

    def test_vram_kv_calc_handles_fit_oom_and_invalid_tp(self) -> None:
        # 70B FP8 on 2x80GB H100 (tp=2): fits cleanly.
        proc_fit = subprocess.run(
            [
                sys.executable,
                str(VRAM_KV_CALC),
                "--params-b", "70",
                "--precision", "fp8",
                "--layers", "80",
                "--attention-heads", "64",
                "--kv-heads", "8",
                "--head-dim", "128",
                "--kv-dtype", "bf16",
                "--max-model-len", "8192",
                "--concurrency", "16",
                "--gpu-vram-gb", "80",
                "--gpu-count", "2",
                "--tp", "2",
                "--json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc_fit.returncode, 0, proc_fit.stderr)
        fit_payload = json.loads(proc_fit.stdout)
        self.assertEqual(fit_payload["schema_version"], "vram_kv_budget/v1")
        self.assertTrue(fit_payload["capacity"]["fits"])
        self.assertTrue(fit_payload["parallelism"]["tp_divisibility_ok"])
        self.assertGreater(fit_payload["capacity"]["max_safe_concurrency_at_max_len"], 16)

        # 70B BF16 on 1x80GB: OOM likely.
        proc_oom = subprocess.run(
            [
                sys.executable,
                str(VRAM_KV_CALC),
                "--params-b", "70",
                "--precision", "bf16",
                "--layers", "80",
                "--attention-heads", "64",
                "--kv-heads", "8",
                "--head-dim", "128",
                "--gpu-vram-gb", "80",
                "--gpu-count", "1",
                "--json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc_oom.returncode, 1)
        oom_payload = json.loads(proc_oom.stdout)
        self.assertEqual(oom_payload["capacity"]["verdict"], "oom_likely")
        self.assertFalse(oom_payload["capacity"]["fits"])

        # Invalid TP divisibility (tp=3 does not divide 64 attention heads).
        proc_tp = subprocess.run(
            [
                sys.executable,
                str(VRAM_KV_CALC),
                "--params-b", "70",
                "--precision", "fp8",
                "--layers", "80",
                "--attention-heads", "64",
                "--kv-heads", "8",
                "--head-dim", "128",
                "--gpu-vram-gb", "80",
                "--gpu-count", "3",
                "--tp", "3",
                "--json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(proc_tp.returncode, 1)
        self.assertEqual(json.loads(proc_tp.stdout)["capacity"]["verdict"], "invalid_tp_divisibility")


if __name__ == "__main__":
    unittest.main()
