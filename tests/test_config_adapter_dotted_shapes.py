from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()
from omh.config_adapter import (
    ensure_external_dir,
    ensure_plugin_enabled,
    external_dirs,
    plugin_enablement,
    plugin_is_enabled,
    remove_external_dir,
)


class DottedConfigShapeTests(unittest.TestCase):
    def test_dotted_external_dirs_read_and_mutate(self) -> None:
        text = "skills.external_dirs: [/keep, /tmp/omh/skills]\n"
        self.assertEqual(external_dirs(text), ["/keep", "/tmp/omh/skills"])
        ensured = ensure_external_dir("skills.external_dirs: [/keep]\n", "/tmp/omh/skills")
        self.assertEqual(external_dirs(ensured.text), ["/keep", "/tmp/omh/skills"])
        removed = remove_external_dir(text, "/tmp/omh/skills")
        self.assertEqual(external_dirs(removed.text), ["/keep"])

    def test_dotted_external_dirs_null_is_supported(self) -> None:
        change = ensure_external_dir("skills.external_dirs: null\n", "/tmp/omh/skills")
        self.assertEqual(external_dirs(change.text), ["/tmp/omh/skills"])

    def test_dotted_plugin_lists_are_read(self) -> None:
        text = "plugins.enabled: [omh, browser]\nplugins.disabled: [legacy]\n"
        self.assertEqual(plugin_enablement(text), {"enabled": ["omh", "browser"], "disabled": ["legacy"]})
        self.assertTrue(plugin_is_enabled(text, "omh"))

    def test_dotted_plugin_mutation_preserves_shape(self) -> None:
        change = ensure_plugin_enabled("plugins.enabled: [browser]\nplugins.disabled: []\n", "omh")
        self.assertEqual(plugin_enablement(change.text), {"enabled": ["browser", "omh"], "disabled": []})
        self.assertIn("plugins.enabled: [browser, omh]", change.text)
        self.assertNotIn("\nplugins:\n", change.text)

    def test_dotted_disabled_plugin_is_not_overridden(self) -> None:
        text = "plugins.enabled: []\nplugins.disabled: [omh]\n"
        change = ensure_plugin_enabled(text, "omh")
        self.assertFalse(change.changed)
        self.assertEqual(change.text, text)

    def test_unsupported_dotted_plugin_mutation_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ensure_plugin_enabled("plugins.enabled: omh\n", "omh")


if __name__ == "__main__":
    unittest.main()
