from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from test_cli import run_cli


class InstalledWorkflowDocsTests(unittest.TestCase):
    def test_filters_workflow_reference_by_manifest_and_writes_output(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / ".omh"
            home.mkdir()
            (home / "manifest.json").write_text(json.dumps({"skills": [{"name": "oh-my-hermes"}, {"name": "not-catalogued"}]}), encoding="utf-8")
            output = Path(tmp) / "installed.md"
            status, stdout, stderr = run_cli(["--omh-home", str(home), "docs", "workflows", "--installed", "--output", str(output)])
            self.assertEqual((status, stderr), (0, ""))
            self.assertEqual(json.loads(stdout)["scope"], "installed")
            rendered = output.read_text(encoding="utf-8")
            self.assertIn("# Installed Workflow Reference", rendered)
            self.assertIn("### oh-my-hermes", rendered)
            self.assertNotIn("not-catalogued", rendered)

    def test_requires_a_manifest(self) -> None:
        with TemporaryDirectory() as tmp:
            status, stdout, stderr = run_cli(["--omh-home", str(Path(tmp) / ".omh"), "docs", "workflows", "--installed"])
            self.assertEqual(status, 2)
            self.assertEqual(stdout, "")
            self.assertIn("require an OMH manifest", stderr)


if __name__ == "__main__":
    unittest.main()
