from __future__ import annotations

import unittest

from _local_package import load_local_package

load_local_package()

from omh.capabilities.keywords import keyword_detector_manifest


class KeywordManifestTests(unittest.TestCase):
    def test_keyword_manifest_exports_invocation_precedence_and_locale_policy(self) -> None:
        manifest = keyword_detector_manifest()

        self.assertEqual(manifest["schema_version"], "keyword_detector_manifest/v1")
        prefixes = {item["prefix"]: item for item in manifest["explicit_invocation_prefixes"]}
        for prefix in ("$", "/", "./", "@"):
            self.assertEqual(prefixes[prefix]["strength"], "exact")
            self.assertEqual(prefixes[prefix]["precedence"], 1)
        self.assertTrue(manifest["conflict_policy"]["explicit_wins"])
        self.assertEqual(manifest["conflict_policy"]["tied_scores"], "clarify")
        self.assertIn("ja", manifest["locale_policy"]["supported_alias_locales"])
        self.assertIn("payment_failure", manifest["locale_policy"]["alias_labels"])

    def test_keyword_manifest_includes_guard_rules_and_skill_triggers(self) -> None:
        manifest = keyword_detector_manifest()
        rules = {item["id"]: item["rule"] for item in manifest["guard_rules"]}
        catalog = {item["id"]: item for item in manifest["guard_policy_catalog"]}
        skills = {item["skill"]: item for item in manifest["natural_language_rules"]}

        self.assertIn("risky_refactor_before_cleanup", rules)
        self.assertIn("planning/review", rules["risky_refactor_before_cleanup"])
        self.assertEqual(catalog["risky_refactor_before_cleanup"]["activation_status"], "active")
        self.assertEqual(catalog["feedback_before_coding"]["activation_status"], "cataloged")
        self.assertIn("ultragoal", skills)
        self.assertIn("$ultragoal", skills["ultragoal"]["triggers"])
        self.assertEqual(skills["ops-observability-card"]["exposure"], "harness_only")
        self.assertFalse(skills["ops-observability-card"]["install_visibility"])
        self.assertTrue(skills["ops-observability-card"]["compatibility_alias"])
