from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _local_package import load_local_package

load_local_package()

from omh.coding.maestro import ExternalHandoffRequest, HermesNativeSelectionError, build_external_handoff  # noqa: E402
from omh.coding.model_discovery import discover_local_models  # noqa: E402
from omh.coding.model_recommendations import resolve_model_recommendation  # noqa: E402
from omh.coding.pi_family_interop import RUNTIME_HOME


class ModelRoutingJourneyTests(unittest.TestCase):
    def test_discovery_to_hermes_and_maestro_keeps_the_owner_boundary(self) -> None:
        with TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            models = home / RUNTIME_HOME / "models.json"
            models.parent.mkdir(parents=True)
            models.write_text(
                json.dumps(
                    {
                        "models": [
                            {"provider": "xai", "model_id": "grok-build-0.1"},
                            {"provider": "apitopia", "model_id": "kimi-k3.1-pro"},
                            {"provider": "google", "model_id": "gemini-4-argon"},
                        ]
                    }
                ),
                encoding="utf-8",
            )

            discovery = discover_local_models(home=home)
            active = [
                {
                    **observation,
                    "status": "confirmed_active",
                }
                for observation in discovery["observations"]
            ]
            hermes = resolve_model_recommendation(
                owner="hermes",
                domain="x_platform_data",
                active_models=active,
            )
            external = resolve_model_recommendation(
                owner="maestro",
                domain="x_platform_data",
                active_models=active,
            )
            handoff = build_external_handoff(
                ExternalHandoffRequest(
                    message="Use Claude Code to implement the X-platform change",
                    profile="claude-code",
                )
            )

        self.assertEqual(hermes["projection"]["kind"], "hermes_native_binding")
        self.assertEqual(hermes["projection"]["binding"], "xai/grok-build-0.1")
        self.assertEqual(external["projection"]["kind"], "maestro_ordered_chain")
        self.assertEqual(external["available_chain"][:3], ["grok-build-0.1", "kimi-k3.1-pro", "gemini-4-argon"])
        self.assertEqual(handoff.capability.profile, "claude-code")
        self.assertEqual(handoff.capability.observation_boundary, "prepared_not_observed")
        self.assertFalse(handoff.capability.executes_work)

    def test_maestro_rejects_hermes_and_missing_recommendations_stay_flexible(self) -> None:
        missing = resolve_model_recommendation(
            owner="hermes",
            category="ultrabrain",
            active_models=[{"provider": "google", "model_id": "gemini-4-argon", "status": "confirmed_active"}],
        )
        unavailable = resolve_model_recommendation(
            owner="hermes",
            category="ultrabrain",
            explicit_model="gpt-5.6-sol",
            active_models=[{"provider": "google", "model_id": "gemini-4-argon", "status": "confirmed_active"}],
        )

        self.assertEqual(missing["status"], "owner_default")
        self.assertTrue(missing["setup_can_continue"])
        # ultrabrain is Fable 5.2 -> Astra -> Opus 5.5 (owner decision,
        # 2026-11-09, Fable 5.2 since 2026-11-10); the shared last resort Opus 5.5 -> GPT-6.1 Sol follows,
        # and the Opus 5.5 it repeats is listed once.
        self.assertEqual(
            missing["inactive_candidates"],
            ["claude-fable-5-2", "gpt-6-astra", "claude-opus-5-5", "gpt-6.1-sol"],
        )
        self.assertEqual(unavailable["status"], "choice_required")
        self.assertTrue(unavailable["setup_can_continue"])
        self.assertEqual(unavailable["requested_model"], "gpt-5.6-sol")
        with self.assertRaises(HermesNativeSelectionError):
            build_external_handoff(ExternalHandoffRequest(message="fix it", profile="hermes"))
