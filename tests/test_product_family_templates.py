from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()
from omh.coding.product_family_templates import product_family_template, validate_product_family_template


class ProductFamilyTemplateTests(unittest.TestCase):
    def test_each_supported_family_is_prepared_only_and_valid(self) -> None:
        for family in ("web", "mobile", "desktop", "api"):
            with self.subTest(family=family):
                template = product_family_template(family)
                self.assertEqual(template["status"], "prepared_not_observed")
                self.assertEqual(validate_product_family_template(template), [])

    def test_unknown_family_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            product_family_template("game-console")
