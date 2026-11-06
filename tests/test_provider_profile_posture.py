from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _cli_harness import run_cli
from _local_package import load_local_package


load_local_package()
from omh.local_store import atomic_write_json
from omh.paths import resolve_paths
from omh.workflows.provider_profile_posture import (
    build_provider_profile_posture,
    parse_provider_profile_posture_input,
    write_provider_profile_posture,
)


def _input_payload() -> dict[str, object]:
    return {
        "schema_version": "provider_profile_posture_input/v1",
        "provider_id": "openai",
        "profile_id": "research-safe",
        "requested_capabilities": ["chat", "tool_call"],
        "secret_requirements": [
            {"name": "OPENAI_API_KEY", "present": "unknown"},
            {"name": "OBSERVABILITY_TOKEN", "present": False},
        ],
        "host_observations": [
            {"kind": "operator_note", "reference": "ticket-123", "observed_at": "2026-07-27T00:00:00Z"}
        ],
    }


class ProviderProfilePostureTests(unittest.TestCase):
    def test_posture_keeps_secret_presence_metadata_and_fixed_prohibitions(self) -> None:
        posture = build_provider_profile_posture(parse_provider_profile_posture_input(_input_payload()))

        self.assertEqual(posture["schema_version"], "provider_profile_posture/v1")
        self.assertEqual(posture["state"], "prepared_not_observed")
        self.assertEqual(posture["requested_capabilities"], ["chat", "tool_call"])
        self.assertEqual(
            posture["allowed_actions"],
            [
                "request_operator_secret_presence_confirmation",
                "request_host_observation_reference",
                "review_external_connector_readiness",
            ],
        )
        self.assertEqual(
            posture["prohibited_actions"],
            [
                "read_secret_value",
                "call_provider",
                "validate_credential",
                "launch_proxy",
                "route_model",
                "create_wallet",
                "execute_payment",
            ],
        )
        self.assertIn("not credential validation", posture["claim_boundary"])
        self.assertNotIn("api-key-value", json.dumps(posture).lower())

    def test_parser_rejects_invalid_identifiers_and_secret_value_fields(self) -> None:
        invalid_identifier = _input_payload()
        invalid_identifier["provider_id"] = "OpenAI"
        with self.assertRaisesRegex(ValueError, "provider_id"):
            parse_provider_profile_posture_input(invalid_identifier)

        secret_value = _input_payload()
        requirements = secret_value["secret_requirements"]
        self.assertIsInstance(requirements, list)
        requirements[0]["value"] = "api-key-value"
        with self.assertRaisesRegex(ValueError, "secret requirement"):
            parse_provider_profile_posture_input(secret_value)

        for secret_reference_value in (
            "sk-live-123456789",
            "AIzaSyDUMMYABCDEFGHIJKLMNOPQRSTUVWX123",
            "npm_12345678901234567890",
            "gho_12345678901234567890",
            "whsec_12345678901234567890",
        ):
            with self.subTest(reference=secret_reference_value):
                secret_reference = _input_payload()
                observations = secret_reference["host_observations"]
                self.assertIsInstance(observations, list)
                observations[0]["reference"] = secret_reference_value
                with self.assertRaisesRegex(ValueError, "safe opaque metadata reference"):
                    parse_provider_profile_posture_input(secret_reference)

        secret_profile = _input_payload()
        secret_profile["profile_id"] = "gho_12345678901234567890"
        with self.assertRaisesRegex(ValueError, "safe opaque metadata reference"):
            parse_provider_profile_posture_input(secret_profile)

    def test_write_uses_the_operations_provider_profile_store(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = resolve_paths(Path(tmp) / ".omh", Path(tmp) / ".hermes")
            posture = build_provider_profile_posture(parse_provider_profile_posture_input(_input_payload()))

            artifact = write_provider_profile_posture(paths, posture)

            self.assertTrue(artifact["written"])
            self.assertTrue(artifact["path"].startswith(str(paths.provider_profile_postures_dir)))
            self.assertTrue(Path(artifact["path"]).exists())
            self.assertTrue(artifact["posture_id"].startswith("provider_profile_"))

    def test_write_rejects_storage_resolving_outside_omh_home(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            paths = resolve_paths(root / ".omh", root / ".hermes")
            paths.omh_home.mkdir()
            outside = root / "outside"
            outside.mkdir()
            paths.operations_dir.symlink_to(outside, target_is_directory=True)
            posture = build_provider_profile_posture(parse_provider_profile_posture_input(_input_payload()))

            with self.assertRaisesRegex(ValueError, "resolve under OMH home"):
                write_provider_profile_posture(paths, posture)

    def test_ops_cli_writes_a_prepared_posture_without_connecting_to_a_provider(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / ".omh"
            input_path = root / "profile.json"
            atomic_write_json(input_path, _input_payload())

            status, stdout, stderr = run_cli(
                [
                    "--omh-home",
                    str(omh_home),
                    "ops",
                    "provider-profile-posture",
                    "--input",
                    str(input_path),
                    "--write",
                ]
            )

            self.assertEqual(status, 0, stderr)
            self.assertEqual(stderr, "")
            posture = json.loads(stdout)
            self.assertEqual(posture["state"], "prepared_not_observed")
            self.assertTrue(posture["artifact"]["written"])
            self.assertIn("not credential validation, provider connectivity", posture["claim_boundary"])


class ProviderProfilePostureSkillTextTests(unittest.TestCase):
    def test_skill_names_the_capabilities_and_command_the_tool_accepts(self):
        from omh.skills.render import builtin_skill_templates
        from omh.workflows.provider_profile_posture import _CAPABILITIES

        body = next(t.content for t in builtin_skill_templates() if t.name == "provider-profile-posture")
        self.assertIn("omh ops provider-profile-posture --input", body)
        listed = body.split("requested capabilities (", 1)[1].split(")", 1)[0]
        self.assertEqual(set(listed.replace(" ", "").split(",")), set(_CAPABILITIES))
        from omh.workflows.provider_profile_posture import (
            PROVIDER_PROFILE_POSTURE_INPUT_SCHEMA_VERSION,
            _INPUT_REQUIRED_KEYS,
            _SECRET_REQUIREMENT_KEYS,
        )

        for key in _INPUT_REQUIRED_KEYS:
            if key != "schema_version":
                self.assertIn(f"`{key}`", body)
        self.assertIn(PROVIDER_PROFILE_POSTURE_INPUT_SCHEMA_VERSION, body)
        self.assertIn("{" + ", ".join(sorted(_SECRET_REQUIREMENT_KEYS)) + "}", body)


if __name__ == "__main__":
    unittest.main()
