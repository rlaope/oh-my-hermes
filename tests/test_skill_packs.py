"""Contract tests for the rebalanced 12-skill core profile and layered opt-in skill packs."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()

from _cli_harness import run_cli
from omh.core.errors import OmhError
from omh.installer import (
    DEFAULT_SKILL_PROFILE,
    install_skill_pack,
    installed_skill_names,
    reconcile_skill_profile,
    skill_profile_report,
)
from omh.paths import resolve_paths
from omh.skill_pack import (
    BESPOKE_SKILL_BODY_NAMES,
    CORE_PROFILE_SKILLS,
    CORE_SKILLS,
    SKILL_PACKS,
    SKILL_PACK_NAMES,
    core_with_packs_skill_names,
    installable_skill_names,
    resolve_skill_pack_names,
)
from omh.skills.context_cost import skill_context_cost_payload
from omh.skills.skill_record import _BESPOKE_BODIES


class LayeredSkillPacksTests(unittest.TestCase):
    def test_default_profile_remains_full_and_core_is_12_high_lift_skills(self) -> None:
        self.assertEqual(DEFAULT_SKILL_PROFILE, "full")
        self.assertEqual(len(CORE_SKILLS), 5)
        self.assertEqual(len(CORE_PROFILE_SKILLS), 12)
        for required in (
            "oh-my-hermes",
            "doctor",
            "skill",
            "cancel",
            "agent-ops-review",
            "plan",
            "code-review",
            "verification-gate",
            "app-debugging",
            "agent-debug",
            "spend-gate",
            "skill-eval",
        ):
            self.assertIn(required, CORE_PROFILE_SKILLS)

    def test_bespoke_body_set_matches_skill_record_registry(self) -> None:
        self.assertEqual(BESPOKE_SKILL_BODY_NAMES, frozenset(_BESPOKE_BODIES))

    def test_every_layered_pack_names_only_installable_skills(self) -> None:
        installable = set(installable_skill_names())
        self.assertEqual(
            SKILL_PACK_NAMES,
            ("engineering", "research-science", "business-ops", "creative-media", "jev"),
        )
        for pack, members in SKILL_PACKS.items():
            with self.subTest(pack=pack):
                self.assertTrue(members)
                self.assertEqual(len(members), len(set(members)), f"duplicate members in {pack}")
                unknown = sorted(set(members) - installable)
                self.assertEqual(unknown, [], f"pack {pack} names non-installable skills")

    def test_resolve_skill_pack_names_fails_closed_on_unknown_pack(self) -> None:
        self.assertEqual(
            resolve_skill_pack_names(["engineering", "jev", "engineering"]),
            ("engineering", "jev"),
        )
        with self.assertRaises(ValueError):
            resolve_skill_pack_names(["does-not-exist"])

    def test_install_core_with_pack_and_reconcile_back_to_core_plus_pack(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            result = install_skill_pack(paths, profile="core", packs=("jev",))
            expected = set(core_with_packs_skill_names(("jev",)))
            self.assertEqual(set(installed_skill_names(paths.skills_dir)), expected)
            self.assertEqual(result["skill_profile"], "core")
            self.assertEqual(result["skill_packs"], ["jev"])
            self.assertEqual(result["skill_profile_state"]["effective_profile"], "core+packs")
            self.assertTrue(result["skill_profile_state"]["matches_requested_profile"])
            self.assertFalse(result["skill_profile_state"]["retained_exception"])

            # Upgrading to full installs everything; explicit reconcile shrinks back to core+jev.
            install_skill_pack(paths, profile="full")
            self.assertEqual(
                set(installed_skill_names(paths.skills_dir)),
                set(installable_skill_names()),
            )
            reconciled = reconcile_skill_profile(paths, target_profile="core", packs=("jev",))
            self.assertEqual(set(installed_skill_names(paths.skills_dir)), expected)
            self.assertEqual(reconciled["target_packs"], ["jev"])
            self.assertEqual(reconciled["profile_state_after"]["effective_profile"], "core+packs")

            report = skill_profile_report(paths)
            self.assertEqual(report["profile_state"]["requested_packs"], ["jev"])
            self.assertEqual(report["reconcilable_skills"], [])

    def test_unknown_pack_raises_omh_error_in_installer(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            with self.assertRaises(OmhError):
                install_skill_pack(paths, profile="core", packs=("nonexistent",))

    def test_cli_install_core_with_pack_and_context_cost_packs_summary(self) -> None:
        with TemporaryDirectory() as tmp:
            omh_home = Path(tmp) / ".omh"
            hermes_home = Path(tmp) / ".hermes"
            rc, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "--hermes-home",
                    str(hermes_home),
                    "install",
                    "--core",
                    "--pack",
                    "creative-media",
                    "--json",
                ],
                output_json=False,
            )
            self.assertEqual(rc, 0, stderr)
            payload = json.loads(stdout)
            self.assertEqual(payload["skill_profile"], "core")
            self.assertEqual(payload["skill_packs"], ["creative-media"])
            self.assertEqual(payload["skill_profile_state"]["effective_profile"], "core+packs")

        cost = skill_context_cost_payload()
        self.assertEqual([item["pack"] for item in cost["packs"]], list(SKILL_PACK_NAMES))
        for item in cost["packs"]:
            self.assertGreater(item["core_plus_pack_skill_count"], len(CORE_PROFILE_SKILLS))


if __name__ == "__main__":
    unittest.main()
