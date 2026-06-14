from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


class PackagingMetadataTests(unittest.TestCase):
    def test_license_uses_modern_spdx_expression(self) -> None:
        metadata = tomllib.loads(Path("pyproject.toml").read_text())
        project = metadata["project"]

        self.assertEqual(project["license"], "MIT")
        self.assertNotIn("License :: OSI Approved :: MIT License", project["classifiers"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
