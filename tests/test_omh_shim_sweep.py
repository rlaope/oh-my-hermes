from __future__ import annotations

import importlib
import unittest

from _local_package import load_local_package

load_local_package()

import omh.system.local_store as canonical_local_store
import omh.system.paths as canonical_paths
import omh.workflows.web_visual_qa as web_visual_qa


class OmhShimSweepTests(unittest.TestCase):
    def test_repointed_web_visual_qa_uses_canonical_system_modules(self) -> None:
        # The straggler was repointed off the flat omh.local_store / omh.paths
        # shims onto the canonical omh.system.* modules. The re-exported symbols
        # must still resolve to the canonical implementations.
        self.assertIs(
            web_visual_qa.atomic_write_json,
            canonical_local_store.atomic_write_json,
        )
        self.assertIs(
            web_visual_qa.ensure_dir,
            canonical_local_store.ensure_dir,
        )
        self.assertIs(
            web_visual_qa.OmhPaths,
            canonical_paths.OmhPaths,
        )

    def test_deleted_flat_shims_are_gone_but_canonical_paths_import(self) -> None:
        # Each swept flat shim had zero flat-path consumers; the canonical deep
        # module must still import cleanly after the shim was removed.
        swept = {
            "hermes_achievements": "omh.workflows.hermes_achievements",
            "product_family_templates": "omh.coding.product_family_templates",
            "product_quality_harnesses": "omh.coding.product_quality_harnesses",
            "project_governance": "omh.coding.project_governance",
            "specialist_work": "omh.quality.specialist_work",
            "specialists": "omh.catalogs.specialists",
        }
        for flat_name, canonical in swept.items():
            with self.subTest(shim=flat_name):
                self.assertIsNotNone(importlib.import_module(canonical))
                with self.assertRaises(ModuleNotFoundError):
                    importlib.import_module(f"omh.{flat_name}")

    def test_retained_facades_still_import(self) -> None:
        # A representative slice of the compatibility facades that stay (they are
        # locked by test_architecture_layout and/or have flat consumers).
        for flat_name in ("paths", "local_store", "learning_candidate", "chat_router"):
            with self.subTest(facade=flat_name):
                module = importlib.import_module(f"omh.{flat_name}")
                self.assertIsNotNone(module)


if __name__ == "__main__":
    unittest.main()
