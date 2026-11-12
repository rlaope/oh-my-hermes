from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE / "lib"))

from omh_live import current_session_argv  # noqa: E402
from runner import run_matrix  # noqa: E402


class EditSurfaceTests(unittest.TestCase):
    def _route(self):
        return {"selected_model": "m", "selected_reasoning_effort": "high", "model_family": "f"}

    def test_default_argv_byte_identical(self) -> None:
        argv = current_session_argv("hermes", route=self._route(), provider="og",
                                    usage_file=Path("u.json"), prompt="p", workspace=Path("w"))
        self.assertEqual(argv[argv.index("--toolsets") + 1], "file,terminal")
        self.assertNotIn("--edit-surface", argv)

    def test_hashline_argv_and_env(self) -> None:
        argv = current_session_argv("hermes", route=self._route(), provider="og",
                                    usage_file=Path("u.json"), prompt="p", workspace=Path("w"),
                                    edit_surface="hashline")
        self.assertEqual(argv[argv.index("--toolsets") + 1], "omh-hashline,terminal")
        self.assertNotIn("file,", argv[argv.index("--toolsets") + 1])

    def test_current_session_env_sets_hashline_flag(self) -> None:
        from omh_live import _current_session_environment
        env = _current_session_environment(Path("w"), "hashline")
        self.assertEqual(env.get("OMH_HASHLINE_TOOLS"), "1")
        env2 = _current_session_environment(Path("w"), "patch")
        self.assertNotIn("OMH_HASHLINE_TOOLS", env2)

    def test_invalid_edit_surface_rejected(self) -> None:
        with self.assertRaises(ValueError):
            current_session_argv("hermes", route=self._route(), provider="og",
                                 usage_file=Path("u.json"), prompt="p", workspace=Path("w"),
                                 edit_surface="foo")

    def test_extra_model_parsing(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(BASE / "bench.py"), "smoke",
             "--extra-model", "id=x/y,provider=og,effort=high,family=kimi"],
            capture_output=True, text=True, check=True,
        )
        self.assertIn("omh_live_model_tool", completed.stdout)

    def test_extra_model_family_is_optional(self) -> None:
        # The route picks the calibration from the model id, so a spec may leave `family=` out.
        with TemporaryDirectory() as root:
            completed = subprocess.run(
                [sys.executable, str(BASE / "bench.py"), "smoke", "--output", str(Path(root) / "runs.jsonl"),
                 "--extra-model", "id=mistral-large-latest,provider=og,effort=high"],
                capture_output=True, text=True, check=False,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("omh_live_model_tool", completed.stdout)

    def test_extra_model_missing_key_rejected(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(BASE / "bench.py"), "smoke", "--extra-model", "id=x/y"],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(completed.returncode, 2)
        self.assertIn("missing required keys", completed.stderr)

    def test_templates_filter_run_matrix(self) -> None:
        manifest = json.loads((BASE / "manifest.json").read_text())
        with TemporaryDirectory() as root:
            output = Path(root) / "runs.jsonl"
            receipt = run_matrix(BASE, manifest, "development", "baseline",
                                 output, templates=["D-RENAME"])
            self.assertEqual(receipt["scheduled"], 1)

    def test_edit_surface_recorded_in_run_record(self) -> None:
        from runner import execute_one
        manifest = json.loads((BASE / "manifest.json").read_text())
        with TemporaryDirectory() as root:
            record = execute_one(BASE, manifest, "development", "D-RENAME", "edit", 7919,
                                 "baseline", Path(root) / "runs.jsonl")
            self.assertIn("edit_surface", record)


if __name__ == "__main__":
    unittest.main()


class EditDirectiveTests(unittest.TestCase):
    def test_directive_names_each_surface_tools_with_identical_wording(self):
        from omh_live import edit_directive

        patch_rule, hashline_rule = edit_directive("patch"), edit_directive("hashline")
        self.assertIn("`patch`", patch_rule)
        self.assertIn("`hashline_edit`", hashline_rule)
        normalized = hashline_rule.replace("hashline_read", "read_file").replace("hashline_edit", "patch")
        self.assertEqual(normalized, patch_rule)
        with self.assertRaises(ValueError):
            edit_directive("other")
