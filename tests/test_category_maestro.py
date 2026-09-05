"""Contracts for category-maestro — operator category->model chains for the
Maestro dispatch lane.

The Hermes-native delegation lane routes per work category through an editable
mixture (`omh model-chains`); `~/.omh/routing/category-maestro.json` is the
same dial for the Maestro lane's dispatchable CLI profiles. The loader never
raises and drops invalid pieces by name; the resolver merges the operator
table over `BUILTIN_CATEGORY_MODELS` for every path that consults it (explicit
category, role, research depth, task scale) and records the basis as
`catalog_kind: "operator_category_config"` plus the config fingerprint; an
absent config leaves every route byte-identical to the built-in resolution.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.coding.category_maestro import (
    CATEGORY_MAESTRO_PROFILES,
    category_maestro_path,
    clear_category_maestro_chain,
    read_category_maestro_config,
    set_category_maestro_chain,
)
from omh.coding.fanout import build_fanout_contract
from omh.coding.fanout_contracts import FanoutContractError
from omh.coding.model_routing import (
    BUILTIN_CATEGORY_MODELS,
    MODEL_CATALOG_KINDS,
    resolve_model_route,
)

_CONFIG = {
    "schema_version": "omh_category_maestro/v1",
    "profiles": {
        "codex": {
            "ultrabrain": ({"model_id": "gpt-5.6-sol", "reasoning_effort": "xhigh"},),
            "deep": ({"model_id": "gpt-5.6-sol", "reasoning_effort": "high"},),
            "quick": ({"model_id": "gpt-5.6-luna", "reasoning_effort": "low"},),
        }
    },
    "fingerprint": {"source": "category-maestro.json", "digest": "feedfacefeedface"},
}


def _write_config(omh_home: Path, profiles: dict) -> Path:
    path = category_maestro_path(omh_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": "omh_category_maestro/v1", "profiles": profiles}),
        encoding="utf-8",
    )
    return path


class CategoryMaestroLoaderTests(unittest.TestCase):
    def test_profiles_cover_exactly_the_builtin_catalog_profiles(self) -> None:
        self.assertEqual(CATEGORY_MAESTRO_PROFILES, tuple(sorted(BUILTIN_CATEGORY_MODELS)))

    def test_missing_and_malformed_documents_read_as_absent(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertIsNone(read_category_maestro_config(home))
            path = category_maestro_path(home)
            path.parent.mkdir(parents=True)
            path.write_text("{not json", encoding="utf-8")
            self.assertIsNone(read_category_maestro_config(home))
            path.write_text(json.dumps({"schema_version": "wrong/v9", "profiles": {}}), encoding="utf-8")
            self.assertIsNone(read_category_maestro_config(home))

    def test_valid_config_reads_with_fingerprint_and_alias_normalization(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            # `brain` is the ulw alias for ultrabrain; the stored table must
            # come back canonical so the resolver's lookup hits it.
            _write_config(
                home,
                {"codex": {"brain": [{"model_id": "gpt-5.6-sol", "reasoning_effort": "xhigh"}]}},
            )
            config = read_category_maestro_config(home)
            self.assertIsNotNone(config)
            self.assertEqual(
                config["profiles"]["codex"]["ultrabrain"],
                ({"model_id": "gpt-5.6-sol", "reasoning_effort": "xhigh"},),
            )
            fingerprint = config["fingerprint"]
            self.assertEqual(fingerprint["source"], "category-maestro.json")
            self.assertEqual(len(fingerprint["digest"]), 16)
            self.assertEqual(config["rejected"], [])

    def test_invalid_pieces_are_dropped_and_named(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_config(
                home,
                {
                    "codex": {
                        "ultrabrain": [{"model_id": "gpt-5.6-sol"}],
                        "no-such-category": [{"model_id": "x"}],
                        "quick": [],
                        "deep": [{"model_id": "bad model id"}],
                    },
                    "not-a-profile": {"quick": [{"model_id": "x"}]},
                },
            )
            config = read_category_maestro_config(home)
            self.assertIsNotNone(config)
            self.assertEqual(list(config["profiles"]), ["codex"])
            self.assertEqual(list(config["profiles"]["codex"]), ["ultrabrain"])
            rejected_text = "\n".join(config["rejected"])
            self.assertIn("no-such-category", rejected_text)
            self.assertIn("not-a-profile", rejected_text)
            self.assertIn("'quick'", rejected_text)
            self.assertIn("'deep'", rejected_text)

    def test_config_that_validates_to_nothing_reads_as_absent(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            _write_config(home, {"codex": {"quick": []}})
            self.assertIsNone(read_category_maestro_config(home))


class CategoryMaestroWriterTests(unittest.TestCase):
    def test_set_then_read_round_trips_and_clear_restores_builtin(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            result = set_category_maestro_chain(
                home,
                "codex",
                "ultrabrain",
                [{"model_id": "gpt-5.6-sol", "reasoning_effort": "xhigh"}],
            )
            self.assertEqual(result["category"], "ultrabrain")
            config = read_category_maestro_config(home)
            self.assertEqual(
                config["profiles"]["codex"]["ultrabrain"][0]["model_id"], "gpt-5.6-sol"
            )
            cleared = clear_category_maestro_chain(home, "codex", "ultrabrain")
            self.assertTrue(cleared["removed"])
            self.assertIsNone(read_category_maestro_config(home))
            again = clear_category_maestro_chain(home, "codex", "ultrabrain")
            self.assertFalse(again["removed"])

    def test_set_rejects_bad_profile_category_and_entries(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            with self.assertRaises(ValueError):
                set_category_maestro_chain(home, "hermes", "quick", [{"model_id": "x"}])
            with self.assertRaises(ValueError):
                set_category_maestro_chain(home, "codex", "no-such", [{"model_id": "x"}])
            with self.assertRaises(ValueError):
                set_category_maestro_chain(home, "codex", "quick", [])
            with self.assertRaises(ValueError):
                set_category_maestro_chain(home, "codex", "quick", [{"model_id": "has space"}])
            with self.assertRaises(ValueError):
                set_category_maestro_chain(
                    home, "codex", "quick", [{"model_id": "ok", "reasoning_effort": "Bad Effort"}]
                )
            # A "model id" with a leading dash would parse as a flag in the
            # spawned CLI's argv; an unbounded effort has no honest shape.
            with self.assertRaises(ValueError):
                set_category_maestro_chain(
                    home, "codex", "quick", [{"model_id": "--dangerously-skip-permissions"}]
                )
            with self.assertRaises(ValueError):
                set_category_maestro_chain(
                    home, "codex", "quick", [{"model_id": "ok", "reasoning_effort": "a" * 33}]
                )

    def test_writers_refuse_an_unrecognized_existing_file(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            path = category_maestro_path(home)
            path.parent.mkdir(parents=True)
            original = json.dumps(
                {
                    "schema_version": "omh_category_maestro/v2",
                    "profiles": {"codex": {"quick": [{"model_id": "keepme"}]}},
                    "notes": "hand written",
                }
            )
            path.write_text(original, encoding="utf-8")
            with self.assertRaises(ValueError):
                set_category_maestro_chain(home, "codex", "quick", [{"model_id": "x"}])
            with self.assertRaises(ValueError):
                clear_category_maestro_chain(home, "codex", "quick")
            self.assertEqual(path.read_text(encoding="utf-8"), original)

    def test_clear_validates_profile_and_a_noop_creates_no_file(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            with self.assertRaises(ValueError):
                clear_category_maestro_chain(home, "no-such-profile", "quick")
            result = clear_category_maestro_chain(home, "codex", "quick")
            self.assertFalse(result["removed"])
            # The file's presence is the routing opt-in; a no-op clear must
            # not create it as a side effect.
            self.assertFalse(category_maestro_path(home).exists())

    def test_pathologically_nested_json_reads_as_absent_not_a_crash(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            path = category_maestro_path(home)
            path.parent.mkdir(parents=True)
            path.write_text("[" * 60000 + "]" * 60000, encoding="utf-8")
            self.assertIsNone(read_category_maestro_config(home))


class CategoryMaestroResolverTests(unittest.TestCase):
    def test_vocabulary_includes_the_operator_catalog_kind(self) -> None:
        self.assertIn("operator_category_config", MODEL_CATALOG_KINDS)

    def test_explicit_category_selects_operator_chain_and_records_basis(self) -> None:
        route = resolve_model_route("codex", requested_category="ultrabrain", category_config=_CONFIG)
        self.assertEqual(route["selected_model"], "gpt-5.6-sol")
        self.assertEqual(route["selected_reasoning_effort"], "xhigh")
        self.assertEqual(route["provenance"], "category_chain_head")
        self.assertEqual(route["catalog_kind"], "operator_category_config")
        self.assertEqual(route["catalog_fingerprint"]["digest"], "feedfacefeedface")
        stages = [entry["stage"] for entry in route["attempted"]]
        self.assertIn("category_config", stages)

    def test_role_chain_derives_from_the_merged_table(self) -> None:
        # brain = (deep, unspecified-low); deep is overridden, the tail is not.
        route = resolve_model_route("codex", role="brain", category_config=_CONFIG)
        self.assertEqual(route["selected_model"], "gpt-5.6-sol")
        self.assertEqual(route["selected_reasoning_effort"], "high")
        self.assertEqual(route["provenance"], "role_chain_head")
        chain_models = [entry["model_id"] for entry in route["chain"]]
        self.assertEqual(chain_models, ["gpt-5.6-sol"])

    def test_depth_and_scale_chains_derive_from_the_merged_table(self) -> None:
        deep = resolve_model_route(
            "codex", role="research", requested_depth="deep", category_config=_CONFIG
        )
        self.assertEqual(deep["selected_model"], "gpt-5.6-sol")
        self.assertEqual(deep["selected_reasoning_effort"], "xhigh")
        small = resolve_model_route(
            "codex", role="implementation", requested_scale="small", category_config=_CONFIG
        )
        self.assertEqual(small["selected_model"], "gpt-5.6-luna")
        self.assertEqual(small["selected_reasoning_effort"], "low")

    def test_requested_model_still_wins_over_the_operator_chain(self) -> None:
        route = resolve_model_route(
            "codex",
            requested_model="explicit-model",
            requested_category="ultrabrain",
            category_config=_CONFIG,
        )
        self.assertEqual(route["selected_model"], "explicit-model")
        self.assertEqual(route["provenance"], "request_named_model")

    def test_unconfigured_profile_keeps_the_builtin_basis(self) -> None:
        route = resolve_model_route("claude-code", role="brain", category_config=_CONFIG)
        self.assertEqual(route["selected_model"], "claude-fable-5-1")
        self.assertEqual(route["catalog_kind"], "built_in_defaults")
        self.assertNotIn("catalog_fingerprint", route)

    def test_absent_config_is_byte_identical_to_todays_resolution(self) -> None:
        for profile in CATEGORY_MAESTRO_PROFILES:
            for kwargs in (
                {"role": "brain"},
                {"requested_category": "quick"},
                {"role": "research", "requested_depth": "deep"},
                {"role": "implementation", "requested_scale": "large"},
                {"requested_model": "explicit", "requested_effort": "high"},
            ):
                with self.subTest(profile=profile, kwargs=kwargs):
                    self.assertEqual(
                        json.dumps(resolve_model_route(profile, **kwargs), sort_keys=True),
                        json.dumps(
                            resolve_model_route(profile, category_config=None, **kwargs),
                            sort_keys=True,
                        ),
                    )

    def test_tests_only_chains_injection_wins_over_operator_config(self) -> None:
        chains = {"codex": {"brain": ({"model_id": "injected", "reasoning_effort": ""},)}}
        route = resolve_model_route("codex", role="brain", chains=chains, category_config=_CONFIG)
        self.assertEqual(route["selected_model"], "injected")
        self.assertEqual(route["catalog_kind"], "built_in_defaults")


class CategoryMaestroFanoutTests(unittest.TestCase):
    def _unit(self, **extra: object) -> dict[str, object]:
        return {
            "unit_id": "core",
            "title": "core unit",
            "owner": "codex",
            "file_scope": ["src/"],
            "depends_on": [],
            **extra,
        }

    def test_unit_category_freezes_the_operator_routed_model(self) -> None:
        contract = build_fanout_contract(
            "route by category",
            [self._unit(category="ultrabrain")],
            category_config=_CONFIG,
        )
        route = contract["units"][0]["handoff"]["model_route"]
        self.assertEqual(route["selected_model"], "gpt-5.6-sol")
        self.assertEqual(route["selected_reasoning_effort"], "xhigh")
        self.assertEqual(route["catalog_kind"], "operator_category_config")

    def test_unit_category_routes_the_builtin_chain_without_config(self) -> None:
        contract = build_fanout_contract(
            "route by category",
            [self._unit(category="ultrabrain")],
        )
        route = contract["units"][0]["handoff"]["model_route"]
        self.assertEqual(route["selected_model"], "gpt-6-astra")
        self.assertEqual(
            [entry["model_id"] for entry in route["chain"]], ["gpt-6-astra", "gpt-5.6-sol"]
        )
        self.assertEqual(route["catalog_kind"], "built_in_defaults")

    def test_unit_scale_survives_normalization_into_routing(self) -> None:
        contract = build_fanout_contract(
            "route by scale",
            [self._unit(role="implementation", scale="small")],
            category_config=_CONFIG,
        )
        route = contract["units"][0]["handoff"]["model_route"]
        self.assertEqual(route["selected_model"], "gpt-5.6-luna")

    def test_unknown_unit_category_fails_the_freeze_by_name(self) -> None:
        with self.assertRaises(FanoutContractError) as caught:
            build_fanout_contract("bad category", [self._unit(category="no-such")])
        self.assertIn("no-such", str(caught.exception))


class CategoryMaestroCliTests(unittest.TestCase):
    def test_set_show_route_clear_round_trip(self) -> None:
        with TemporaryDirectory() as tmp:
            base = ["--omh-home", str(Path(tmp) / ".omh")]
            status, stdout, stderr = run_cli(
                base + ["coding", "category-maestro", "set", "codex", "ultrabrain", "gpt-5.6-sol:xhigh"],
                output_json=False,
            )
            self.assertEqual((status, stderr), (0, ""))
            self.assertIn("gpt-5.6-sol xhigh", stdout)

            status, stdout, stderr = run_cli(
                base + ["coding", "category-maestro", "show", "--json"], output_json=False
            )
            self.assertEqual((status, stderr), (0, ""))
            report = json.loads(stdout)
            self.assertTrue(report["configured"])
            cell = report["profiles"]["codex"]["ultrabrain"]
            self.assertEqual(cell["source"], "operator")
            self.assertEqual(cell["chain"][0]["model_id"], "gpt-5.6-sol")
            self.assertEqual(report["profiles"]["codex"]["deep"]["source"], "built_in")

            status, stdout, stderr = run_cli(
                base + ["coding", "model-route", "--executor", "codex", "--category", "ultrabrain", "--json"],
                output_json=False,
            )
            self.assertEqual((status, stderr), (0, ""))
            route = json.loads(stdout)
            self.assertEqual(route["selected_model"], "gpt-5.6-sol")
            self.assertEqual(route["catalog_kind"], "operator_category_config")

            status, stdout, stderr = run_cli(
                base + ["coding", "category-maestro", "clear", "codex", "ultrabrain"],
                output_json=False,
            )
            self.assertEqual((status, stderr), (0, ""))
            status, stdout, stderr = run_cli(
                base + ["coding", "model-route", "--executor", "codex", "--category", "ultrabrain", "--json"],
                output_json=False,
            )
            self.assertEqual((status, stderr), (0, ""))
            self.assertEqual(json.loads(stdout)["selected_model"], "gpt-6-astra")

    def test_colon_tagged_model_ids_stay_intact_and_efforts_still_split(self) -> None:
        with TemporaryDirectory() as tmp:
            base = ["--omh-home", str(Path(tmp) / ".omh")]
            status, stdout, stderr = run_cli(
                base
                + [
                    "coding", "category-maestro", "set", "codex", "quick",
                    "qwen2.5-coder:7b", "gpt-5.6-luna:low",
                ],
                output_json=False,
            )
            self.assertEqual((status, stderr), (0, ""))
            status, stdout, stderr = run_cli(
                base + ["coding", "category-maestro", "show", "--json"], output_json=False
            )
            self.assertEqual((status, stderr), (0, ""))
            chain = json.loads(stdout)["profiles"]["codex"]["quick"]["chain"]
            self.assertEqual(
                chain,
                [
                    {"model_id": "qwen2.5-coder:7b", "reasoning_effort": ""},
                    {"model_id": "gpt-5.6-luna", "reasoning_effort": "low"},
                ],
            )

    def test_rejected_config_pieces_reach_stderr_on_route_commands(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / ".omh"
            _write_config(
                home,
                {
                    "codex": {
                        "ultrabrain": [{"model_id": "gpt-5.6-sol"}],
                        "no-such-category": [{"model_id": "x"}],
                    }
                },
            )
            status, _stdout, stderr = run_cli(
                ["--omh-home", str(home), "coding", "model-route", "--executor", "codex", "--role", "brain", "--json"],
                output_json=False,
            )
            self.assertEqual(status, 0)
            self.assertIn("no-such-category", stderr)

    def test_set_rejects_unknown_vocabulary_with_a_named_error(self) -> None:
        with TemporaryDirectory() as tmp:
            base = ["--omh-home", str(Path(tmp) / ".omh")]
            status, _stdout, stderr = run_cli(
                base + ["coding", "category-maestro", "set", "codex", "no-such", "model-x"],
                output_json=False,
            )
            self.assertNotEqual(status, 0)
            self.assertIn("no-such", stderr)

    def test_show_names_where_catalogless_profiles_route_categories(self) -> None:
        # pi/omo-runtime is deliberately absent from this table (one-basis
        # rule); show must say where its categories DO come from instead of
        # reading as "no category routing there".
        with TemporaryDirectory() as tmp:
            base = ["--omh-home", str(Path(tmp) / ".omh")]
            status, stdout, stderr = run_cli(
                base + ["coding", "category-maestro", "show"], output_json=False
            )
            self.assertEqual((status, stderr), (0, ""))
            self.assertIn("omo-runtime (host CLI: pi/senpi)", stdout)
            self.assertIn("--from-inventory", stdout)
            status, stdout, stderr = run_cli(
                base + ["coding", "category-maestro", "show", "--json"], output_json=False
            )
            self.assertEqual((status, stderr), (0, ""))
            note = json.loads(stdout)["catalogless_note"]
            self.assertIn("omo-runtime", note)
            self.assertIn("omo config", note)

    def test_interview_refuses_without_a_terminal_and_names_the_scriptable_path(self) -> None:
        with TemporaryDirectory() as tmp:
            base = ["--omh-home", str(Path(tmp) / ".omh")]
            status, _stdout, stderr = run_cli(
                base + ["coding", "category-maestro", "interview"], output_json=False
            )
            self.assertEqual(status, 2)
            self.assertIn("category-maestro set", stderr)
            self.assertIn("category-maestro show", stderr)

    def test_interview_applies_clear_custom_and_keep_choices(self) -> None:
        from unittest.mock import patch

        from omh.coding.model_routing import MODEL_CATEGORIES

        with TemporaryDirectory() as tmp:
            home = Path(tmp) / ".omh"
            set_category_maestro_chain(
                home, "codex", "ultrabrain", [{"model_id": "old-pick", "reasoning_effort": "xhigh"}]
            )
            # claude-code first (skipped), then codex: ultrabrain has an
            # override so option 2 is the built-in default (clears it); every
            # other category's option 2 is the custom entry — `deep` gets one,
            # the rest keep current via Enter.
            answers = ["", "y"]
            for category in MODEL_CATEGORIES:
                if category == "ultrabrain":
                    answers.append("2")
                elif category == "deep":
                    answers.extend(["2", "gpt-5.6-sol:xhigh, gpt-5.6-terra"])
                else:
                    answers.append("")
            responses = iter(answers)
            with (
                patch("omh.commands.coding._stdin_is_tty", return_value=True),
                patch("builtins.input", side_effect=lambda *_: next(responses)),
            ):
                status, stdout, stderr = run_cli(
                    ["--omh-home", str(home), "coding", "category-maestro", "interview"],
                    output_json=False,
                )
            self.assertEqual((status, stderr), (0, ""), stdout)
            self.assertIn("Saved 2 chains", stdout)
            config = read_category_maestro_config(home)
            self.assertEqual(list(config["profiles"]), ["codex"])
            self.assertEqual(
                config["profiles"]["codex"],
                {
                    "deep": (
                        {"model_id": "gpt-5.6-sol", "reasoning_effort": "xhigh"},
                        {"model_id": "gpt-5.6-terra", "reasoning_effort": ""},
                    )
                },
            )

    def test_run_exposes_the_category_flag(self) -> None:
        from contextlib import redirect_stdout
        from io import StringIO

        from omh.cli import main

        buffer = StringIO()
        with redirect_stdout(buffer), self.assertRaises(SystemExit) as caught:
            main(["coding", "run", "--help"])
        self.assertEqual(caught.exception.code, 0)
        self.assertIn("--category", buffer.getvalue())


class CategoryMaestroSetupIntegrationTests(unittest.TestCase):
    def test_setup_maestro_step_offers_and_runs_the_category_interview(self) -> None:
        import argparse
        from types import SimpleNamespace
        from unittest.mock import patch

        from omh.commands import coding as coding_module
        from omh.commands import setup as setup_module

        with TemporaryDirectory() as tmp:
            paths = SimpleNamespace(omh_home=Path(tmp) / ".omh")
            args = argparse.Namespace()
            detected = {
                profile: {"binary_present": profile == "codex", "login_marker": "unknown"}
                for profile in setup_module.EXTERNAL_CLI_PROFILES
            }
            calls: list[object] = []
            with (
                patch.object(setup_module, "_detect_external_cli_profiles", return_value=detected),
                # First yes: set up the maestro lane; second yes: walk the
                # category table now.
                patch.object(setup_module, "_ask_yes_no", side_effect=[True, True]),
                patch.object(
                    coding_module,
                    "category_maestro_interview",
                    side_effect=lambda received: calls.append(received) or 0,
                ),
            ):
                from contextlib import redirect_stdout
                from io import StringIO

                with redirect_stdout(StringIO()):
                    setup_module._ask_maestro_delegation_choice(args, paths, "en")
            self.assertEqual(calls, [paths])

    def test_setup_maestro_step_declining_the_interview_changes_nothing(self) -> None:
        import argparse
        from types import SimpleNamespace
        from unittest.mock import patch

        from omh.commands import coding as coding_module
        from omh.commands import setup as setup_module

        with TemporaryDirectory() as tmp:
            paths = SimpleNamespace(omh_home=Path(tmp) / ".omh")
            args = argparse.Namespace()
            detected = {
                profile: {"binary_present": profile == "codex", "login_marker": "unknown"}
                for profile in setup_module.EXTERNAL_CLI_PROFILES
            }
            calls: list[object] = []
            with (
                patch.object(setup_module, "_detect_external_cli_profiles", return_value=detected),
                patch.object(setup_module, "_ask_yes_no", side_effect=[True, False]),
                patch.object(
                    coding_module,
                    "category_maestro_interview",
                    side_effect=lambda received: calls.append(received) or 0,
                ),
            ):
                from contextlib import redirect_stdout
                from io import StringIO

                with redirect_stdout(StringIO()):
                    setup_module._ask_maestro_delegation_choice(args, paths, "en")
            self.assertEqual(calls, [])
            self.assertIsNone(read_category_maestro_config(Path(tmp) / ".omh"))

    def test_onboarding_language_keys_exist_in_every_locale(self) -> None:
        from omh.commands.language import MESSAGES

        for code, table in MESSAGES.items():
            for key in (
                "maestro_delegation_pointers",
                "maestro_category_prompt",
                "maestro_category_note",
                "model_setup_maestro_hint",
            ):
                with self.subTest(locale=code, key=key):
                    self.assertIn(key, table)
        for key in ("maestro_delegation_pointers", "model_setup_maestro_hint"):
            for code, table in MESSAGES.items():
                with self.subTest(locale=code, key=key):
                    self.assertIn("category-maestro", table[key])


if __name__ == "__main__":
    unittest.main()
