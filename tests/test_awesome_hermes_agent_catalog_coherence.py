from __future__ import annotations

import json
from importlib.resources import files
import unittest

from omh.catalogs.awesome_hermes_agent import (
    CATALOG_SCHEMA_VERSION,
    awesome_hermes_catalog,
    awesome_hermes_items,
)


_SOURCE_FIELDS = (
    "repo",
    "url",
    "default_branch",
    "commit",
    "readme_sha256",
    "retrieved_at",
    "claim_boundary",
)


class AwesomeHermesAgentCatalogCoherenceTests(unittest.TestCase):
    def _raw_catalog(self) -> dict[str, object]:
        resource = files("omh.catalogs").joinpath("awesome_hermes_agent_catalog.json")
        return json.loads(resource.read_text(encoding="utf-8"))

    def test_catalog_loads_clean_via_module_loader(self) -> None:
        catalog = awesome_hermes_catalog()

        self.assertEqual(catalog.to_dict()["schema_version"], CATALOG_SCHEMA_VERSION)
        self.assertTrue(catalog.items)

    def test_declared_item_count_matches_parsed_items(self) -> None:
        raw = self._raw_catalog()
        items = awesome_hermes_items()

        self.assertEqual(raw["item_count"], len(raw["items"]))
        self.assertEqual(raw["item_count"], len(items))

    def test_source_block_fields_are_present_and_non_empty(self) -> None:
        source = self._raw_catalog()["source"]

        self.assertIsInstance(source, dict)
        for field in _SOURCE_FIELDS:
            with self.subTest(field=field):
                value = source.get(field)
                self.assertIsInstance(value, str)
                self.assertTrue(value.strip())

    def test_item_ids_are_unique(self) -> None:
        ids = [item.id for item in awesome_hermes_items()]

        self.assertEqual(len(ids), len(set(ids)))


if __name__ == "__main__":
    unittest.main()
