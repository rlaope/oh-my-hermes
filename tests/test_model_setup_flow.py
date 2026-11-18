from __future__ import annotations

import json
import os
import sys
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from _cli_harness import run_cli
from omh.coding.hermes_model_config import (
    HermesModelConfigInspection,
    HermesModelConfigReceipt,
    ProviderPresence,
)
from omh.commands import setup as setup_commands
from omh.commands.language import tr
from omh.commands.main import build_parser
from omh.commands.model_setup_projections import provider_next_actions
from omh.coding.pi_family_interop import RUNTIME_CONFIG_FILES, RUNTIME_HOME
from omh.coding.model_discovery_adapters import RUNTIME_CONFIG_SOURCE


def _inspection(
    config_path: Path,
    *,
    aliases: dict[str, str] | None = None,
) -> HermesModelConfigInspection:
    return HermesModelConfigInspection(
        hermes="hermes",
        config_path=config_path,
        config_digest="before-digest",
        config_check_ok=True,
        model_aliases={},
        model_dot_aliases=aliases or {},
        providers=(
            ProviderPresence(
                provider_id="openai",
                auth_present=True,
                auth_status_ok=True,
                plugin_present=False,
            ),
            ProviderPresence(
                provider_id="google",
                auth_present=True,
                auth_status_ok=True,
                plugin_present=False,
            ),
            ProviderPresence(
                provider_id="openrouter",
                auth_present=True,
                auth_status_ok=True,
                plugin_present=False,
            ),
        ),
        commands=(),
    )


# Records which home each call acted on, in a log outside every home, and
# answers the read-only inspection plus `config set` from files under
# $HERMES_HOME -- so a write lands in whichever home the call was given.
_HOME_RECORDING_HERMES = """
import json
import os
from pathlib import Path
import sys

home = Path(os.environ["HERMES_HOME"])
args = sys.argv[1:]
with open(os.environ["HERMES_CALL_LOG"], "a", encoding="utf-8") as stream:
    stream.write(json.dumps({"home": str(home), "args": args}) + "\\n")
aliases_path = home / "model-aliases.json"
aliases = json.loads(aliases_path.read_text(encoding="utf-8")) if aliases_path.exists() else {}
if args == ["config", "path"]:
    print(home / "config.yaml")
elif args[:3] == ["config", "get", "model.aliases"]:
    print(json.dumps(aliases))
elif args[:2] == ["config", "get"]:
    raise SystemExit(1)
elif args == ["config", "check"]:
    print("Configuration OK")
elif args[:2] == ["auth", "list"]:
    print("openai (1 credentials):")
elif args[:2] == ["auth", "status"]:
    raise SystemExit(0 if args[2] == "openai" else 1)
elif args[:2] == ["config", "set"] and args[2].startswith("model.aliases."):
    aliases[args[2].removeprefix("model.aliases.")] = args[3]
    aliases_path.write_text(json.dumps(aliases), encoding="utf-8")
else:
    raise SystemExit(f"unexpected command: {args}")
"""


def _discovery(
    observations: list[dict[str, str]],
    *,
    truncated: bool = False,
) -> dict[str, object]:
    return {
        "schema_version": "model_discovery/v1",
        "sources": {
            "codex": {
                "status": "truncated" if truncated else "observed_before",
                "truncated_reasons": ["record_count"] if truncated else [],
            }
        },
        "observations": observations,
        "observation_count": len(observations),
        "claim_boundary": "metadata only",
    }


class ModelSetupFlowTests(unittest.TestCase):
    def test_setup_parser_exposes_explicit_model_activation_flags(self) -> None:
        args = build_parser().parse_args(
            [
                "setup",
                "--model-setup",
                "--confirm-model",
                "openai/gpt-5.6-sol",
                "--model-alias",
                "main=openai/gpt-5.6-sol",
                "--apply-model-config",
                "--model-config-digest",
                "digest",
                "--allow-model-alias-collision",
            ]
        )

        self.assertTrue(args.model_setup)
        self.assertEqual(args.confirm_model, ["openai/gpt-5.6-sol"])
        self.assertEqual(args.model_alias, ["main=openai/gpt-5.6-sol"])
        self.assertTrue(args.apply_model_config)
        self.assertEqual(args.model_config_digest, "digest")
        self.assertTrue(args.allow_model_alias_collision)

    def test_observed_before_is_not_confirmation_and_explicit_unavailable_freezes_choice(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / ".hermes" / "config.yaml"
            config_path.parent.mkdir()
            config_path.write_text("{}\n", encoding="utf-8")
            observations = [
                {
                    "source": "codex",
                    "provider": "openai",
                    "model_id": "gpt-5.6-sol",
                    "variant": "",
                    "timestamp": "",
                    "status": "observed_before",
                }
            ]
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            with patch.object(
                setup_commands,
                "discover_local_models",
                return_value=_discovery(observations),
            ), patch.object(
                setup_commands,
                "inspect_hermes_model_config",
                return_value=_inspection(config_path),
            ):
                status, stdout, stderr = run_cli(
                    base
                    + [
                        "setup",
                        "--model-setup",
                        "--model-alias",
                        "main=openai/gpt-5.6-sol",
                        "--json",
                    ],
                    output_json=False,
                )

        self.assertEqual((status, stderr), (0, ""))
        activation = json.loads(stdout)["steps"]["model_activation"]
        self.assertEqual(activation["status"], "choice_required")
        self.assertEqual(activation["candidates"][0]["status"], "observed_before")
        self.assertEqual(activation["recommendations"]["main"]["status"], "choice_required")
        self.assertIsNone(activation["preview"])
        self.assertEqual(activation["next_action"], "confirm_active_model")

    def test_no_confirmed_candidate_completes_with_owner_defaults_and_no_write(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / ".hermes" / "config.yaml"
            config_path.parent.mkdir()
            config_path.write_text("{}\n", encoding="utf-8")
            before = config_path.read_bytes()

            with patch.object(
                setup_commands,
                "discover_local_models",
                return_value=_discovery([]),
            ), patch.object(
                setup_commands,
                "inspect_hermes_model_config",
                return_value=_inspection(config_path),
            ), patch.object(
                setup_commands,
                "apply_hermes_model_config",
            ) as apply_config:
                status, stdout, stderr = run_cli(
                    [
                        "--omh-home",
                        str(root / ".omh"),
                        "--hermes-home",
                        str(root / ".hermes"),
                        "setup",
                        "--dry-run",
                        "--skip-apply",
                        "--no-menubar",
                        "--model-setup",
                        "--no-interactive",
                        "--json",
                    ],
                    output_json=False,
                )

            activation = json.loads(stdout)["steps"]["model_activation"]
            self.assertEqual((status, stderr), (0, ""))
            self.assertEqual(activation["status"], "defaulted")
            self.assertEqual(activation["next_action"], "model_setup_complete")
            self.assertEqual(
                activation["recommendations"]["main"]["status"],
                "owner_default",
            )
            self.assertTrue(
                all(
                    recommendation["status"] == "owner_default"
                    for recommendation in activation["recommendations"][
                        "hermes_native"
                    ]["categories"].values()
                )
            )
            self.assertTrue(
                all(
                    recommendation["status"] == "owner_default"
                    for recommendation in activation["recommendations"][
                        "maestro"
                    ]["categories"].values()
                )
            )
            self.assertIsNone(activation["preview"])
            self.assertEqual(activation["apply"]["status"], "not_requested")
            self.assertEqual(config_path.read_bytes(), before)
            apply_config.assert_not_called()

    def test_unmatched_confirmed_model_still_completes_with_owner_default(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / ".hermes" / "config.yaml"
            config_path.parent.mkdir()
            config_path.write_text("{}\n", encoding="utf-8")
            before = config_path.read_bytes()
            qwen = {
                "source": "hermes",
                "provider": "qwen-oauth",
                "model_id": "qwen3-coder",
                "variant": "",
                "timestamp": "",
                "status": "observed_before",
            }

            with patch.object(
                setup_commands,
                "discover_local_models",
                return_value=_discovery([qwen]),
            ), patch.object(
                setup_commands,
                "inspect_hermes_model_config",
                return_value=_inspection(config_path),
            ), patch.object(
                setup_commands,
                "apply_hermes_model_config",
            ) as apply_config:
                status, stdout, stderr = run_cli(
                    [
                        "--omh-home",
                        str(root / ".omh"),
                        "--hermes-home",
                        str(root / ".hermes"),
                        "setup",
                        "--dry-run",
                        "--skip-apply",
                        "--no-menubar",
                        "--model-setup",
                        "--no-interactive",
                        "--confirm-model",
                        "qwen-oauth/qwen3-coder",
                        "--json",
                    ],
                    output_json=False,
                )

            activation = json.loads(stdout)["steps"]["model_activation"]
            self.assertEqual((status, stderr), (0, ""))
            self.assertEqual(activation["status"], "defaulted")
            self.assertEqual(activation["next_action"], "model_setup_complete")
            self.assertEqual(activation["recommendations"]["main"]["status"], "owner_default")
            self.assertIsNone(activation["preview"])
            self.assertEqual(activation["apply"]["status"], "not_requested")
            self.assertEqual(config_path.read_bytes(), before)
            apply_config.assert_not_called()

    def test_confirmed_qwen_and_gemini_only_can_preview_without_writing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / ".hermes" / "config.yaml"
            config_path.parent.mkdir()
            config_path.write_text("{}\n", encoding="utf-8")
            observations = [
                {
                    "source": "codex",
                    "provider": provider,
                    "model_id": model,
                    "variant": "",
                    "timestamp": "",
                    "status": "observed_before",
                }
                for provider, model in (
                    ("openrouter", "qwen3-coder"),
                    ("google", "gemini-3.1-pro"),
                )
            ]
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            with patch.object(
                setup_commands,
                "discover_local_models",
                return_value=_discovery(observations),
            ), patch.object(
                setup_commands,
                "inspect_hermes_model_config",
                return_value=_inspection(config_path),
            ), patch.object(setup_commands, "apply_hermes_model_config") as apply_config:
                status, stdout, stderr = run_cli(
                    base
                    + [
                        "setup",
                        "--model-setup",
                        "--confirm-model",
                        "openrouter/qwen3-coder",
                        "--confirm-model",
                        "google/gemini-3.1-pro",
                        "--model-alias",
                        "main=openrouter/qwen3-coder",
                        "--json",
                    ],
                    output_json=False,
                )

            self.assertEqual((status, stderr), (0, ""))
            activation = json.loads(stdout)["steps"]["model_activation"]
            self.assertEqual(activation["status"], "preview_ready")
            self.assertEqual(
                {candidate["status"] for candidate in activation["candidates"]},
                {"confirmed_active"},
            )
            self.assertEqual(
                activation["preview"]["changes"],
                {"main": "openrouter/qwen3-coder"},
            )
            self.assertEqual(activation["apply"]["status"], "declined")
            self.assertEqual(activation["verification"]["status"], "not_run")
            self.assertNotIn("model:\n  aliases:", config_path.read_text(encoding="utf-8"))
            apply_config.assert_not_called()

    def test_rich_models_project_every_category_for_hermes_and_maestro(self) -> None:
        observations = [
            {
                "source": source,
                "provider": provider,
                "model_id": model,
                "variant": "",
                "timestamp": "",
                "status": "observed_before",
            }
            for provider, model, source in (
                ("openai", "gpt-6.2-sol", "codex"),
                ("openai", "gpt-5.6-terra", "codex"),
                ("apitopia", "kimi-k3", RUNTIME_CONFIG_SOURCE),
                ("anthropic", "claude-fable-5", "claude-code"),
                ("sglang", "glm-5.2", RUNTIME_CONFIG_SOURCE),
            )
        ]
        providers = tuple(
            ProviderPresence(provider, True, True, False)
            for provider in ("anthropic", "apitopia", "openai", "sglang")
        )
        inspection = HermesModelConfigInspection(
            hermes="hermes",
            config_path=Path("/tmp/config.yaml"),
            config_digest="before-digest",
            config_check_ok=True,
            model_aliases={},
            model_dot_aliases={},
            providers=providers,
            commands=(),
        )
        confirmed = [
            f"{observation['provider']}/{observation['model_id']}"
            for observation in observations
        ]
        with patch.object(
            setup_commands, "discover_local_models", return_value=_discovery(observations)
        ), patch.object(
            setup_commands, "inspect_hermes_model_config", return_value=inspection
        ):
            status, stdout, stderr = run_cli(
                [
                    "--omh-home", "/tmp/.omh", "--hermes-home", "/tmp/.hermes",
                    "setup", "--dry-run", "--skip-apply", "--no-menubar", "--model-setup",
                    *[item for model in confirmed for item in ("--confirm-model", model)],
                    "--json",
                ],
                output_json=False,
            )

        self.assertEqual((status, stderr), (0, ""))
        recommendations = json.loads(stdout)["steps"]["model_activation"]["recommendations"]
        expected = {
            "ultrabrain", "deep", "architect", "unspecified-high", "unspecified-low",
            "quick", "writing", "visual-engineering", "artistry",
            "capable", "simple-work", "deep-work",
            "google-search", "x-search", "review", "swarm", "forensics", "synthesize",
        }
        self.assertEqual(set(recommendations["hermes_native"]["categories"]), expected)
        self.assertEqual(set(recommendations["maestro"]["categories"]), expected)
        self.assertEqual(
            recommendations["hermes_native"]["categories"]["ultrabrain"]["projection"]["kind"],
            "hermes_native_binding",
        )
        self.assertEqual(
            recommendations["maestro"]["categories"]["ultrabrain"]["projection"]["kind"],
            "maestro_ordered_chain",
        )

    def test_pi_family_import_and_qwen_gemini_next_actions_are_explicit(self) -> None:
        observations = [
            {
                "source": RUNTIME_CONFIG_SOURCE,
                "provider": provider,
                "model_id": model,
                "variant": "",
                "timestamp": "",
                "status": "observed_before",
            }
            for provider, model in (("qwen", "qwen3-coder"), ("google", "gemini-3.1-pro"))
        ]
        with TemporaryDirectory() as temp:
            home = Path(temp)
            (home / RUNTIME_HOME).mkdir()
            (home / RUNTIME_HOME / RUNTIME_CONFIG_FILES[0]).write_text(
                json.dumps({"categories": {"deep": {
                    "model": "qwen/qwen3-coder",
                    "variant": "high",
                    "fallback_models": [{"model": "google/gemini-3.1-pro"}],
                }}}),
                encoding="utf-8",
            )
            inspection = HermesModelConfigInspection(
                hermes="hermes",
                config_path=home / "config.yaml",
                config_digest="before-digest",
                config_check_ok=True,
                model_aliases={},
                model_dot_aliases={},
                providers=(ProviderPresence("qwen", True, True, False),),
                commands=(),
            )
            with patch("omh.commands.model_setup_flow.Path.home", return_value=home), patch.object(
                setup_commands, "discover_local_models", return_value=_discovery(observations)
            ), patch.object(
                setup_commands, "inspect_hermes_model_config", return_value=inspection
            ):
                status, stdout, stderr = run_cli(
                    [
                        "--omh-home", str(home / ".omh"),
                        "--hermes-home", str(home / ".hermes"),
                        "setup", "--dry-run", "--skip-apply", "--no-menubar",
                        "--model-setup", "--import-category-overrides",
                        "--confirm-model", "qwen/qwen3-coder",
                        "--confirm-model", "google/gemini-3.1-pro", "--json",
                    ],
                    output_json=False,
                )

        self.assertEqual((status, stderr), (0, ""))
        activation = json.loads(stdout)["steps"]["model_activation"]
        recommendations = activation["recommendations"]
        self.assertEqual(recommendations["category_overrides"]["status"], "imported")
        self.assertEqual(
            recommendations["hermes_native"]["categories"]["deep"]["selected"]["model_alias"],
            "qwen3-coder",
        )
        self.assertEqual(
            activation["provider_next_actions"],
            [
                {"provider": "google", "status": "auth_missing",
                 "next_action": "hermes auth login google"},
                {"provider": "qwen", "status": "ready", "next_action": ""},
            ],
        )
        serialized = json.dumps(recommendations).lower()
        self.assertNotIn("token", serialized)
        self.assertNotIn("session", serialized)

    def test_model_activation_flags_require_explicit_model_setup(self) -> None:
        status, _stdout, stderr = run_cli(
            ["setup", "--confirm-model", "openai/gpt-5.6-sol"],
            output_json=False,
        )

        self.assertEqual(status, 2)
        self.assertIn("require --model-setup", stderr)

    def test_alias_collision_requires_explicit_collision_choice(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / ".hermes" / "config.yaml"
            config_path.parent.mkdir()
            config_path.write_text("{}\n", encoding="utf-8")
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            command = [
                "setup",
                "--model-setup",
                "--confirm-model",
                "openai/gpt-5.6-sol",
                "--model-alias",
                "main=openai/gpt-5.6-sol",
                "--json",
            ]

            with patch.object(
                setup_commands,
                "discover_local_models",
                return_value=_discovery([]),
            ), patch.object(
                setup_commands,
                "inspect_hermes_model_config",
                return_value=_inspection(config_path, aliases={"main": "anthropic/claude-opus-5"}),
            ):
                status, _stdout, stderr = run_cli(base + command, output_json=False)
                allowed_status, allowed_stdout, allowed_stderr = run_cli(
                    base + command[:-1] + ["--allow-model-alias-collision", "--json"],
                    output_json=False,
                )

        self.assertEqual(status, 2)
        self.assertIn("collision refused", stderr)
        self.assertEqual((allowed_status, allowed_stderr), (0, ""))
        preview = json.loads(allowed_stdout)["steps"]["model_activation"]["preview"]
        self.assertEqual(preview["changes"]["main"], "openai/gpt-5.6-sol")

    def test_apply_requires_digest_then_reports_adapter_verification(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / ".hermes" / "config.yaml"
            config_path.parent.mkdir()
            config_path.write_text("{}\n", encoding="utf-8")
            inspection = _inspection(config_path)
            receipt = HermesModelConfigReceipt(
                verified=True,
                before_digest="before-digest",
                after_digest="after-digest",
                commands=(("hermes", "config", "set", "model.aliases.main", "openai/gpt-5.6-sol"),),
                inspection=inspection,
            )
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            command = [
                "setup",
                "--model-setup",
                "--confirm-model",
                "openai/gpt-5.6-sol",
                "--model-alias",
                "main=openai/gpt-5.6-sol",
                "--apply-model-config",
                "--json",
            ]

            with patch.object(
                setup_commands,
                "discover_local_models",
                return_value=_discovery([]),
            ), patch.object(
                setup_commands,
                "inspect_hermes_model_config",
                return_value=inspection,
            ), patch.object(
                setup_commands,
                "apply_hermes_model_config",
                return_value=receipt,
            ) as apply_config:
                missing_status, _stdout, missing_stderr = run_cli(
                    base + command,
                    output_json=False,
                )
                # The approval names the file and the change: the preview prints it.
                _status, preview_stdout, _stderr = run_cli(
                    base + [part for part in command if part != "--apply-model-config"],
                    output_json=False,
                )
                approval = json.loads(preview_stdout)["steps"]["model_activation"]["preview"]["approval_digest"]
                status, stdout, stderr = run_cli(
                    base + command[:-1] + ["--model-config-digest", approval, "--json"],
                    output_json=False,
                )

        self.assertEqual(missing_status, 2)
        self.assertIn("--model-config-digest", missing_stderr)
        self.assertEqual((status, stderr), (0, ""))
        activation = json.loads(stdout)["steps"]["model_activation"]
        self.assertEqual(activation["status"], "verified")
        self.assertEqual(activation["apply"]["status"], "applied")
        self.assertEqual(activation["verification"]["status"], "verified")
        apply_config.assert_called_once()

    def test_human_setup_output_shows_scan_truncation(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / ".hermes" / "config.yaml"
            config_path.parent.mkdir()
            config_path.write_text("{}\n", encoding="utf-8")
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]

            with patch.object(
                setup_commands,
                "discover_local_models",
                return_value=_discovery([], truncated=True),
            ), patch.object(
                setup_commands,
                "inspect_hermes_model_config",
                return_value=_inspection(config_path),
            ):
                status, stdout, stderr = run_cli(
                    base + ["setup", "--model-setup"],
                    output_json=False,
                )

        self.assertEqual((status, stderr), (0, ""))
        self.assertIn("Scanning local model metadata", stdout)
        self.assertIn("truncated: record_count", stdout)

    def test_interactive_shows_preview_before_apply_confirmation(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / ".hermes" / "config.yaml"
            config_path.parent.mkdir()
            config_path.write_text("{}\n", encoding="utf-8")
            base = ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes")]
            events: list[str] = []

            with patch.object(
                setup_commands,
                "discover_local_models",
                return_value=_discovery([]),
            ), patch.object(
                setup_commands,
                "inspect_hermes_model_config",
                return_value=_inspection(config_path),
            ), patch.object(
                setup_commands,
                "_ask_yes_no",
                side_effect=lambda *args, **kwargs: events.append("confirm") or False,
            ), patch.object(
                setup_commands,
                "_print_model_preview_review",
                side_effect=lambda *args, **kwargs: events.append("preview"),
            ):
                status, _stdout, stderr = run_cli(
                    base
                    + [
                        "setup",
                        "--model-setup",
                        "--confirm-model",
                        "openai/gpt-5.6-sol",
                        "--model-alias",
                        "main=openai/gpt-5.6-sol",
                        "--interactive",
                        "--json",
                    ],
                    output_json=False,
                )

        self.assertEqual((status, stderr), (0, ""))
        self.assertEqual(events, ["preview", "confirm"])

    def test_next_actions_send_a_providers_entry_to_its_key_not_a_login(self) -> None:
        # Given: issue #2882's machine, `mistral` under Hermes `providers:` with
        # its key unobservable, next to an unconfigured provider.
        inspection = HermesModelConfigInspection(
            hermes="hermes",
            config_path=Path("config.yaml"),
            config_digest="before-digest",
            config_check_ok=True,
            model_aliases={},
            model_dot_aliases={},
            providers=(
                ProviderPresence(
                    "mistral", False, True, False,
                    provider_entry=True, credential_env="MISTRAL_API_KEY",
                ),
                ProviderPresence("google", False, True, False),
            ),
            commands=(),
        )

        # When: both are confirmed.
        actions = provider_next_actions({"mistral/large", "google/gemini"}, inspection)

        # Then: the providers: entry is never sent to `hermes auth login`, which
        # answers Unknown provider for it; the unconfigured one still is.
        self.assertEqual(
            actions,
            [
                {"provider": "google", "status": "auth_missing",
                 "next_action": "hermes auth login google"},
                {
                    "provider": "mistral",
                    "status": "credential_not_observable",
                    "next_action": "set MISTRAL_API_KEY in the environment omh runs in, "
                    "or add a pool with `hermes auth add mistral`",
                },
            ],
        )

    def test_next_actions_name_the_custom_provider_instead_of_a_bare_custom_login(self) -> None:
        # Given: issue #1998's custom-pool machine, where the configured name
        # carries the pool auth and bare `custom` carries none.
        inspection = HermesModelConfigInspection(
            hermes="hermes",
            config_path=Path("config.yaml"),
            config_digest="before-digest",
            config_check_ok=True,
            model_aliases={},
            model_dot_aliases={},
            providers=(
                ProviderPresence("9router", True, True, False),
                ProviderPresence("custom", False, True, False),
            ),
            commands=(),
        )

        # When: both spellings of the gateway model are confirmed.
        actions = provider_next_actions(
            {"9router/clv/kimi-k3", "custom/clv/kimi-k3"}, inspection
        )

        # Then: the named provider is ready and bare `custom` is not sent to a login.
        self.assertEqual(
            actions,
            [
                {"provider": "9router", "status": "ready", "next_action": ""},
                {
                    "provider": "custom",
                    "status": "custom_provider_name_required",
                    "next_action": "use the configured custom provider name as the prefix: <name>/<model>",
                },
            ],
        )

    def _recording_hermes(self, root: Path) -> tuple[Path, Path]:
        bin_dir = root / "bin"
        bin_dir.mkdir()
        hermes = bin_dir / "hermes"
        hermes.write_text(
            f"#!{sys.executable}\n" + textwrap.dedent(_HOME_RECORDING_HERMES).lstrip(),
            encoding="utf-8",
        )
        hermes.chmod(0o755)
        return bin_dir, root / "hermes-calls.jsonl"

    @unittest.skipIf(os.name == "nt", "the stub is a shebang script resolved as `hermes` on PATH")
    def test_dry_run_apply_reports_the_commands_and_runs_no_mutation(self) -> None:
        # Given: a target home with a config, and a preview digest for one alias.
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / ".hermes"
            target.mkdir()
            (target / "config.yaml").write_text("{}\n", encoding="utf-8")
            bin_dir, call_log = self._recording_hermes(root)
            base = [
                "--omh-home",
                str(root / ".omh"),
                "--hermes-home",
                str(target),
                "setup",
                "--dry-run",
                "--no-menubar",
                "--model-setup",
                "--confirm-model",
                "openai/gpt-5",
                "--model-alias",
                "main=openai/gpt-5",
                "--no-interactive",
                "--json",
            ]
            environment = {
                "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
                "HERMES_HOME": str(target),
                "HERMES_CALL_LOG": str(call_log),
            }
            with patch.dict(os.environ, environment), patch.object(
                setup_commands,
                "discover_local_models",
                return_value=_discovery([]),
            ):
                status, stdout, stderr = run_cli(base, output_json=False)
                self.assertEqual((status, stderr), (0, ""))
                digest = json.loads(stdout)["steps"]["model_activation"]["preview"]["approval_digest"]
                # When: the apply is asked for under --dry-run.
                status, stdout, stderr = run_cli(
                    base + ["--apply-model-config", "--model-config-digest", digest],
                    output_json=False,
                )

            # Then: the would-apply argv is reported and no Hermes call mutated anything.
            self.assertEqual((status, stderr), (0, ""))
            payload = json.loads(stdout)
            activation = payload["steps"]["model_activation"]
            self.assertTrue(payload["dry_run"])
            self.assertEqual(
                activation["apply"],
                {"status": "dry_run", "commands": [["hermes", "config", "set", "model.aliases.main", "openai/gpt-5"]]},
            )
            self.assertFalse(activation["verification"]["verified"])
            calls = [json.loads(line)["args"] for line in call_log.read_text(encoding="utf-8").splitlines()]
            self.assertEqual([call for call in calls if call[:2] in (["config", "set"], ["config", "unset"])], [])
            self.assertFalse((target / "model-aliases.json").exists())

    @unittest.skipIf(os.name == "nt", "the stub is a shebang script resolved as `hermes` on PATH")
    def test_missing_hermes_config_is_a_classified_status_not_a_traceback(self) -> None:
        # Given: a fresh Hermes home; a dry run never creates its config.yaml.
        for label, flags in (("dry_run", ["--dry-run"]), ("skip_apply", ["--skip-apply"])):
            with self.subTest(run=label), TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                target = root / ".hermes"
                bin_dir, call_log = self._recording_hermes(root)
                environment = {
                    "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
                    "HERMES_HOME": str(target),
                    "HERMES_CALL_LOG": str(call_log),
                }
                with patch.dict(os.environ, environment), patch.object(
                    setup_commands,
                    "discover_local_models",
                    return_value=_discovery([]),
                ):
                    # When: the model step runs, scripted and then for a person.
                    status, stdout, stderr = run_cli(
                        ["--omh-home", str(root / ".omh"), "--hermes-home", str(target), "setup", *flags,
                         "--no-menubar", "--model-setup", "--no-interactive", "--json"],
                        output_json=False,
                    )
                    human_status, human_stdout, _ = run_cli(
                        ["--omh-home", str(root / ".omh"), "--hermes-home", str(target), "setup", *flags,
                         "--no-menubar", "--model-setup", "--no-interactive"],
                        output_json=False,
                    )

                # Then: a classified status, a next action, and an exit code that is not success.
                self.assertEqual((status, stderr), (3, ""))
                self.assertEqual(human_status, 3)
                activation = json.loads(stdout)["steps"]["model_activation"]
                self.assertEqual(activation["status"], "hermes_config_missing")
                self.assertEqual(activation["config_path"], str(target / "config.yaml"))
                self.assertEqual(activation["apply"]["status"], "not_run")
                if label == "dry_run":
                    self.assertEqual(activation["next_action"], "rerun_without_dry_run")
                    self.assertIn("A real `omh setup` creates that file", human_stdout)
                else:
                    self.assertEqual(activation["next_action"], "create_hermes_config_then_rerun_model_setup")
                    self.assertIn("without --skip-apply", human_stdout)

    @unittest.skipIf(os.name == "nt", "the stub is a shebang script resolved as `hermes` on PATH")
    def test_a_failing_hermes_command_is_classified_not_a_traceback(self) -> None:
        # Given: a Hermes on PATH whose `config path` exits nonzero, or hangs.
        failing_hermes = (
            "import os, sys, time\n"
            "if sys.argv[1:] == ['config', 'path']:\n"
            "    if os.environ['HERMES_STUB_MODE'] == 'hang':\n"
            "        time.sleep(30)\n"
            "    raise SystemExit(2)\n"
            "raise SystemExit(0)\n"
        )
        for mode in ("nonzero", "hang"):
            with self.subTest(mode=mode), TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                bin_dir = root / "bin"
                bin_dir.mkdir()
                hermes = bin_dir / "hermes"
                hermes.write_text(f"#!{sys.executable}\n" + failing_hermes, encoding="utf-8")
                hermes.chmod(0o755)
                environment = {
                    "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
                    "HERMES_HOME": str(root / ".hermes"),
                    "HERMES_STUB_MODE": mode,
                }
                with patch.dict(os.environ, environment), patch.object(
                    setup_commands,
                    "discover_local_models",
                    return_value=_discovery([]),
                ), patch("omh.coding.hermes_model_config._COMMAND_TIMEOUT_SECONDS", 1):
                    # When: setup runs the model step.
                    status, stdout, stderr = run_cli(
                        ["--omh-home", str(root / ".omh"), "--hermes-home", str(root / ".hermes"), "setup",
                         "--dry-run", "--no-menubar", "--model-setup", "--no-interactive", "--json"],
                        output_json=False,
                    )

                # Then: a classified failure, exit 1, and `ok` says the same.
                self.assertEqual((status, stderr), (1, ""))
                payload = json.loads(stdout)
                activation = payload["steps"]["model_activation"]
                self.assertEqual(activation["status"], "hermes_command_failed")
                self.assertIn("config path", activation["reason"])
                self.assertEqual(activation["next_action"], "check_hermes_config_commands_then_rerun_model_setup")
                self.assertFalse(payload["ok"])

    @unittest.skipIf(os.name == "nt", "the stub is a shebang script resolved as `hermes` on PATH")
    def test_ok_and_the_state_record_agree_with_the_exit_code(self) -> None:
        # Given: a real run whose model step cannot read Hermes' config.
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / ".hermes"
            bin_dir, call_log = self._recording_hermes(root)
            environment = {
                "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
                "HERMES_HOME": str(target),
                "HERMES_CALL_LOG": str(call_log),
            }
            with patch.dict(os.environ, environment), patch.object(
                setup_commands,
                "discover_local_models",
                return_value=_discovery([]),
            ):
                status, stdout, stderr = run_cli(
                    ["--omh-home", str(root / ".omh"), "--hermes-home", str(target), "setup",
                     "--skip-apply", "--no-menubar", "--model-setup", "--no-interactive", "--json"],
                    output_json=False,
                )

            # Then: neither the payload nor the state record calls exit 3 a success.
            self.assertEqual((status, stderr), (3, ""))
            self.assertFalse(json.loads(stdout)["ok"])
            state = json.loads((root / ".omh" / "runtime" / "state.json").read_text(encoding="utf-8"))
            self.assertFalse(state["last_setup"]["ok"])

    @unittest.skipIf(os.name == "nt", "the stub is a shebang script resolved as `hermes` on PATH")
    def test_model_step_acts_on_the_target_hermes_home_not_the_ambient_one(self) -> None:
        # Given: the shell points HERMES_HOME at one home, setup targets another.
        with TemporaryDirectory() as tmp:
            # Resolved, because setup resolves the home (macOS /var -> /private/var).
            root = Path(tmp).resolve()
            target, ambient, bin_dir = root / "target-hermes", root / "ambient-hermes", root / "bin"
            for directory in (target, ambient, bin_dir):
                directory.mkdir()
            (target / "config.yaml").write_text("{}\n", encoding="utf-8")
            (ambient / "config.yaml").write_text("{}\n", encoding="utf-8")
            ambient_before = sorted(path.name for path in ambient.iterdir())
            call_log = root / "hermes-calls.jsonl"
            hermes = bin_dir / "hermes"
            hermes.write_text(
                f"#!{sys.executable}\n" + textwrap.dedent(_HOME_RECORDING_HERMES).lstrip(),
                encoding="utf-8",
            )
            hermes.chmod(0o755)
            base = [
                "--omh-home",
                str(root / ".omh"),
                "--hermes-home",
                str(target),
                "setup",
                "--skip-apply",
                "--no-menubar",
                "--model-setup",
                "--confirm-model",
                "openai/gpt-5",
                "--model-alias",
                "main=openai/gpt-5",
                "--no-interactive",
                "--json",
            ]
            environment = {
                "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
                "HERMES_HOME": str(ambient),
                "HERMES_CALL_LOG": str(call_log),
            }
            with patch.dict(os.environ, environment), patch.object(
                setup_commands,
                "discover_local_models",
                return_value=_discovery([]),
            ):
                # When: setup previews, then applies that preview by its digest.
                status, stdout, stderr = run_cli(base, output_json=False)
                self.assertEqual((status, stderr), (0, ""))
                digest = json.loads(stdout)["steps"]["model_activation"]["preview"]["approval_digest"]
                status, stdout, stderr = run_cli(
                    base + ["--apply-model-config", "--model-config-digest", digest],
                    output_json=False,
                )

            # Then: every Hermes call saw the target home, the alias landed
            # there, and the ambient home was neither read nor written.
            self.assertEqual((status, stderr), (0, ""))
            activation = json.loads(stdout)["steps"]["model_activation"]
            self.assertEqual(activation["verification"]["status"], "verified")
            self.assertEqual(activation["inspection"]["config_path"], str(target / "config.yaml"))
            calls = [json.loads(line) for line in call_log.read_text(encoding="utf-8").splitlines()]
            self.assertIn(["config", "set", "model.aliases.main", "openai/gpt-5"], [call["args"] for call in calls])
            self.assertEqual({call["home"] for call in calls}, {str(target)})
            self.assertEqual(
                json.loads((target / "model-aliases.json").read_text(encoding="utf-8")),
                {"main": "openai/gpt-5"},
            )
            self.assertEqual(sorted(path.name for path in ambient.iterdir()), ambient_before)

    def test_setup_without_hermes_on_path_reports_hermes_unavailable(self) -> None:
        # Given: a machine whose Hermes is managed by a hosted wrapper, so no
        # `hermes` resolves on PATH. The real inspection adapter runs here.
        for label, flags in (
            ("scripted", ["--no-interactive", "--json"]),
            ("interactive", ["--interactive"]),
        ):
            with self.subTest(path=label), TemporaryDirectory() as tmp:
                root = Path(tmp)
                empty_bin = root / "bin"
                empty_bin.mkdir()
                # The run_cli stdin is a StringIO; the interactive subtest
                # stands for a terminal, which `--interactive` now requires.
                with patch.dict(os.environ, {"PATH": str(empty_bin), "HOME": str(root)}), patch.object(
                    setup_commands,
                    "discover_local_models",
                    return_value=_discovery([]),
                ), patch.object(setup_commands, "_wizard_has_terminal", return_value=True):
                    # When: setup runs the model step.
                    status, stdout, stderr = run_cli(
                        [
                            "--omh-home",
                            str(root / ".omh"),
                            "--hermes-home",
                            str(root / ".hermes"),
                            "setup",
                            "--no-menubar",
                            "--model-setup",
                            *flags,
                        ],
                        output_json=False,
                    )

                # Then: the missing executable is a classified status with a
                # next action, and the exit code does not call it success.
                self.assertEqual((status, stderr), (3, ""))
                if label == "scripted":
                    activation = json.loads(stdout)["steps"]["model_activation"]
                    self.assertEqual(activation["status"], "hermes_unavailable")
                    self.assertEqual(activation["next_action"], "install_hermes_then_rerun_model_setup")
                    self.assertEqual(activation["apply"]["status"], "not_run")
                    self.assertFalse(activation["verification"]["verified"])
                else:
                    self.assertIn("Model activation status: hermes_unavailable", stdout)
                    self.assertIn("rerun `omh setup --model-setup`", stdout)
                    self.assertNotIn("owner default remains active", stdout)

    def _recording_environment(self, root: Path, target: Path) -> tuple[dict[str, str], Path]:
        bin_dir, call_log = self._recording_hermes(root)
        environment = {
            "PATH": str(bin_dir) + os.pathsep + os.environ.get("PATH", ""),
            "HERMES_HOME": str(target),
            "HERMES_CALL_LOG": str(call_log),
        }
        return environment, call_log

    @staticmethod
    def _mutating_calls(call_log: Path) -> list[list[str]]:
        if not call_log.exists():
            return []
        calls = [json.loads(line)["args"] for line in call_log.read_text(encoding="utf-8").splitlines()]
        return [call for call in calls if call[:2] in (["config", "set"], ["config", "unset"])]

    @unittest.skipIf(os.name == "nt", "chmod 000 does not make a file unreadable on Windows")
    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0, "root reads a mode-000 file")
    def test_an_unreadable_config_is_not_reported_as_missing(self) -> None:
        # Given: one home with no config.yaml, one whose config.yaml exists but cannot be read.
        for case in ("missing", "unreadable"):
            with self.subTest(case=case), TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                target = root / ".hermes"
                target.mkdir()
                if case == "unreadable":
                    config = target / "config.yaml"
                    config.write_text("{}\n", encoding="utf-8")
                    # Unlinking needs the directory's permissions, not the file's,
                    # so the temporary directory still cleans up.
                    config.chmod(0)
                environment, _call_log = self._recording_environment(root, target)
                argv = ["--omh-home", str(root / ".omh"), "--hermes-home", str(target), "setup",
                        "--dry-run", "--skip-apply", "--no-menubar", "--model-setup", "--no-interactive"]
                with patch.dict(os.environ, environment), patch.object(
                    setup_commands,
                    "discover_local_models",
                    return_value=_discovery([]),
                ):
                    # When: a dry run reaches the model step.
                    status, stdout, stderr = run_cli(argv + ["--json"], output_json=False)
                    human_status, human_stdout, _ = run_cli(argv, output_json=False)

                # Then: only a file that is absent is described as one a real setup creates.
                self.assertEqual((status, stderr, human_status), (3, "", 3))
                activation = json.loads(stdout)["steps"]["model_activation"]
                if case == "missing":
                    self.assertEqual(activation["status"], "hermes_config_missing")
                    self.assertEqual(activation["next_action"], "rerun_without_dry_run")
                    self.assertIn("A real `omh setup` creates that file", human_stdout)
                else:
                    self.assertEqual(activation["status"], "hermes_config_unreadable")
                    self.assertEqual(activation["next_action"], "fix_hermes_config_permissions_then_rerun")
                    self.assertIn("exists but could not be read", human_stdout)
                    self.assertNotIn("A real `omh setup` creates that file", human_stdout)

    @unittest.skipIf(os.name == "nt", "the stub is a shebang script resolved as `hermes` on PATH")
    def test_dry_run_with_a_wrong_digest_is_refused_with_the_adapter_message(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / ".hermes"
            target.mkdir()
            (target / "config.yaml").write_text("{}\n", encoding="utf-8")
            environment, call_log = self._recording_environment(root, target)
            with patch.dict(os.environ, environment), patch.object(
                setup_commands,
                "discover_local_models",
                return_value=_discovery([]),
            ):
                status, _stdout, stderr = run_cli(
                    ["--omh-home", str(root / ".omh"), "--hermes-home", str(target), "setup", "--dry-run",
                     "--no-menubar", "--model-setup", "--confirm-model", "openai/gpt-5", "--model-alias",
                     "main=openai/gpt-5", "--no-interactive", "--json", "--apply-model-config",
                     "--model-config-digest", "0" * 64],
                    output_json=False,
                )

            # The dry run checks the digest the way a real apply would, and still writes nothing.
            self.assertEqual(status, 2)
            self.assertIn("expected digest does not match the preview digest", stderr)
            self.assertEqual(self._mutating_calls(call_log), [])

    @unittest.skipIf(os.name == "nt", "the stub is a shebang script resolved as `hermes` on PATH")
    def test_interactive_dry_run_apply_lists_the_commands_and_mutates_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            target = root / ".hermes"
            target.mkdir()
            (target / "config.yaml").write_text("{}\n", encoding="utf-8")
            environment, call_log = self._recording_environment(root, target)
            prompts: list[str] = []
            with patch.dict(os.environ, environment), patch.object(
                setup_commands,
                "discover_local_models",
                return_value=_discovery([]),
            ), patch.object(
                setup_commands,
                "_ask_yes_no",
                side_effect=lambda prompt, *args, **kwargs: prompts.append(prompt) or True,
            ):
                # When: a person accepts the apply question during a dry run.
                status, stdout, stderr = run_cli(
                    ["--omh-home", str(root / ".omh"), "--hermes-home", str(target), "setup", "--dry-run",
                     "--no-menubar", "--model-setup", "--confirm-model", "openai/gpt-5", "--model-alias",
                     "main=openai/gpt-5", "--interactive"],
                    output_json=False,
                )

            # Then: the question says nothing is written, the summary lists the
            # would-run command, and no Hermes call mutated anything.
            self.assertEqual((status, stderr), (0, ""))
            self.assertEqual(prompts, [tr("en", "model_setup_apply_prompt_dry_run")])
            self.assertIn("Dry run, would run: hermes config set model.aliases.main openai/gpt-5", stdout)
            self.assertEqual(self._mutating_calls(call_log), [])
            self.assertFalse((target / "model-aliases.json").exists())


if __name__ == "__main__":
    unittest.main()
