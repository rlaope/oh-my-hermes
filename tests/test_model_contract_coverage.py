from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.coding.model_contract_coverage import (  # noqa: E402
    MODEL_CONTRACT_COVERAGE_SCHEMA_VERSION,
    build_model_contract_coverage,
    coverage_exit_code,
)


_ASTRA_FORMS = (
    "openai/gpt-6-astra",
    "openai/gpt-6-astra-fast",
    "openai/gpt-6-astra-flex",
    "openai/gpt-6-astra-pro",
    "openai/gpt-6-astra-pro-fast",
    "openai/gpt-6-astra-pro-flex",
)


def _inventory(models: tuple[str, ...], *, status: str = "observed") -> dict[str, object]:
    return {
        "schema_version": "model_inventory_snapshot/v1",
        "executor_profile": "codex",
        "inventory_status": status,
        "provenance": {
            "source": "host_catalog_fixture",
            "digest": "host-supplied-digest-01",
        },
        "models": list(models),
    }


class CoverageMatrixTests(unittest.TestCase):
    def test_every_contract_names_its_docs(self) -> None:
        from omh.coding.model_contract_coverage import _MODEL_DOCS
        from omh.coding.model_contracts import MODEL_CONTRACTS

        # A contract without a docs row reports its docs dimension `missing`
        # although the contract itself is covered; keep the two key sets one.
        self.assertEqual(set(_MODEL_DOCS), set(MODEL_CONTRACTS))

    def test_new_generation_contracts_cover_effort_and_price(self) -> None:
        rows = {
            row["requested_model"]: row
            for row in build_model_contract_coverage(
                _inventory(
                    (
                        "openai/gpt-6-luna",
                        "anthropic/claude-opus-5-5",
                        "anthropic/claude-opus-5",
                        "openai/gpt-6-sol",
                        "openai/gpt-5.6-sol",
                    )
                )
            )["comparison"]["models"]
        }
        luna = rows["openai/gpt-6-luna"]
        self.assertEqual(luna["status"], "exact")
        self.assertEqual(luna["dimensions"]["effort"]["floor"], "none")
        self.assertEqual(luna["dimensions"]["price"]["status"], "documented_list")
        opus = rows["anthropic/claude-opus-5-5"]
        self.assertEqual(opus["status"], "exact")
        self.assertEqual(opus["dimensions"]["effort"]["floor"], "low")
        self.assertIn("off", opus["dimensions"]["effort"]["unsupported_efforts"])
        sol = rows["openai/gpt-6-sol"]
        self.assertEqual(sol["status"], "exact")
        self.assertEqual(sol["dimensions"]["effort"]["floor"], "none")
        self.assertEqual(sol["dimensions"]["price"]["status"], "documented_list")
        # The previous generation keeps no contract.
        self.assertEqual(rows["anthropic/claude-opus-5"]["status"], "missing")
        self.assertEqual(rows["openai/gpt-5.6-sol"]["status"], "missing")

    def test_deepseek_pointer_inherits_the_exact_contract_and_routed_legacy_ids_stay_missing(self) -> None:
        inventory = _inventory(
            (
                "deepseek/deepseek-v4.1-flash",
                "deepseek/deepseek-flash",
                "deepseek/deepseek-v4-flash",
            )
        )
        rows = {
            row["requested_model"]: row
            for row in build_model_contract_coverage(inventory)["comparison"]["models"]
        }
        self.assertEqual(rows["deepseek/deepseek-v4.1-flash"]["status"], "exact")
        pointer = rows["deepseek/deepseek-flash"]
        self.assertEqual(pointer["status"], "declared_inheritance")
        self.assertEqual(pointer["contract_model_id"], "deepseek-v4.1-flash")
        self.assertEqual(pointer["dimensions"]["effort"]["floor"], "low")
        self.assertEqual(pointer["dimensions"]["effort"]["unsupported_efforts"], {})
        self.assertEqual(pointer["dimensions"]["calibration"]["high_effort"], "model_specific")
        # The projection lists every category whose chain names the alias:
        # simple-work joined on 2026-09-11, deep dropped it on 2026-10-13
        # (a Flash budget model does not fit the strong tier), and swarm
        # joined on 2026-10-28 with it at the head.
        self.assertEqual(
            pointer["dimensions"]["category_projection"]["categories"],
            ["simple-work", "swarm", "unspecified-low"],
        )
        self.assertEqual(
            pointer["dimensions"]["provider_eligibility"]["families"],
            ["deepseek", "openrouter", "opencode"],
        )
        self.assertEqual(pointer["dimensions"]["price"]["status"], "documented_list")
        self.assertEqual(pointer["dimensions"]["docs"]["status"], "covered")
        # The vendor routes v4-flash to V4.1 Flash on its own API; the catalog
        # does not turn that wire routing into an inherited contract.
        self.assertEqual(rows["deepseek/deepseek-v4-flash"]["status"], "missing")

    def test_jev_reports_effort_category_and_provider_as_honestly_missing(self) -> None:
        """Three dimensions report `missing` for Jev and all three are right.

        `effort` is missing because the model has no effort parameter;
        `category_projection` and `provider_eligibility` are missing because
        the model is in no shipped chain, which is the decision, not an
        oversight. The only lever that would turn any of them green is an
        invented rung, an invented chain entry, or an `intentional_exclusion`
        row -- and an exclusion would say OMH deliberately does not cover a
        model it does cover, which is a different and false claim. This test
        exists so nobody greens the row by reaching for one of them.
        """
        rows = {
            row["requested_model"]: row
            for row in build_model_contract_coverage(
                _inventory(("jev-1.13.0", "typesafe/jev-latest"))
            )["comparison"]["models"]
        }
        exact = rows["jev-1.13.0"]
        self.assertEqual(exact["status"], "exact")
        self.assertEqual(rows["typesafe/jev-latest"]["status"], "declared_inheritance")
        for requested, row in rows.items():
            with self.subTest(model=requested):
                self.assertEqual(row["contract_model_id"], "jev-1.13.0")
                self.assertEqual(row["dimensions"]["effort"]["status"], "missing")
                self.assertEqual(row["dimensions"]["effort"]["reasoning_efforts"], [])
                self.assertEqual(row["dimensions"]["category_projection"]["status"], "missing")
                self.assertEqual(row["dimensions"]["provider_eligibility"]["status"], "missing")
                # What IS covered, so the row is not read as an unfinished
                # onboarding: the contract, its documentation, and its price.
                self.assertEqual(row["dimensions"]["contract"]["status"], "covered")
                self.assertEqual(row["dimensions"]["docs"]["status"], "covered")
                self.assertEqual(row["dimensions"]["price"]["status"], "documented_list")
                self.assertEqual(row["dimensions"]["family_recognition"]["family"], "jev")
        self.assertEqual(exact["dimensions"]["price"]["prices_usd_per_mtok"]["output"], 0.0)

    def test_jev_data_handling_and_calibration_are_read_like_every_other_row(self) -> None:
        """The two dimensions a reader of the Jev row will misread, pinned.

        `data_handling` also reports `missing`, and the docs say so is not
        about this model: it is compared here against a generative contracted
        row so the claim stays true whichever way the dimension later moves.
        `calibration` reports `covered` through the generic fallback, which
        records that generic discipline applies -- not that a model taking no
        prompt was calibrated. The provenance is the assertion that matters:
        a `model_specific` reading here would mean somebody added the
        per-family entry `MODEL_OPTI.md` says must not exist.
        """
        rows = {
            row["requested_model"]: row
            for row in build_model_contract_coverage(
                _inventory(("jev-1.13.0", "gpt-6-astra"))
            )["comparison"]["models"]
        }
        jev = rows["jev-1.13.0"]["dimensions"]
        generative = rows["gpt-6-astra"]["dimensions"]
        self.assertEqual(jev["data_handling"]["status"], generative["data_handling"]["status"])
        self.assertEqual(jev["calibration"]["status"], "covered")
        self.assertEqual(jev["calibration"]["high_effort"], "family_or_generic")
        self.assertEqual(jev["calibration"]["composition"], "family_or_generic")

    def test_astra_catalog_reports_exact_declared_and_unknown_rows_by_dimension(self) -> None:
        inventory = _inventory(
            (
                *_ASTRA_FORMS,
                "openai/gpt-6-astra-turbo",
                "openai/gpt-6-astra-2",
                "gateway/provider-only-astra",
                # A provider that serves only the dated snapshot (the shape a
                # user reported on 2026-09-11 for gpt-5.6-terra); the audit
                # must count it, not crash on the third provenance.
                "openai/gpt-6-astra-2026-08-01",
            )
        )
        report = build_model_contract_coverage(
            inventory,
            intentional_exclusions=("gateway/provider-only-astra",),
        )

        self.assertEqual(report["schema_version"], MODEL_CONTRACT_COVERAGE_SCHEMA_VERSION)
        comparison = report["comparison"]
        rows = {row["requested_model"]: row for row in comparison["models"]}
        self.assertEqual(rows[_ASTRA_FORMS[0]]["status"], "exact")
        snapshot = rows["openai/gpt-6-astra-2026-08-01"]
        self.assertEqual(snapshot["status"], "dated_snapshot")
        self.assertEqual(snapshot["contract_model_id"], "gpt-6-astra")
        self.assertEqual(snapshot["dimensions"]["calibration"]["high_effort"], "model_specific")
        for model_id in _ASTRA_FORMS[1:]:
            row = rows[model_id]
            with self.subTest(model_id=model_id):
                self.assertEqual(row["status"], "declared_inheritance")
                self.assertEqual(row["contract_model_id"], "gpt-6-astra")
                self.assertEqual(row["dimensions"]["effort"]["status"], "covered")
                self.assertEqual(
                    row["dimensions"]["calibration"]["high_effort"],
                    "model_specific",
                )
                self.assertEqual(
                    row["dimensions"]["calibration"]["composition"],
                    "model_specific",
                )
                # GPT-6 Astra left every shipped chain on 2026-11-18 (GPT-6.2
                # Astra took its architect, forensics, and ultrabrain slots),
                # and both dimensions are read from the shipped chains, so the
                # retired id and its declared aliases report them missing; it
                # keeps its contract, price, and docs.
                self.assertEqual(row["dimensions"]["provider_eligibility"]["families"], [])
                self.assertEqual(row["dimensions"]["provider_eligibility"]["status"], "missing")
                self.assertEqual(row["dimensions"]["category_projection"]["categories"], [])
                self.assertEqual(row["dimensions"]["price"]["status"], "documented_list")
                self.assertEqual(row["dimensions"]["docs"]["status"], "covered")

        self.assertEqual(
            rows["openai/gpt-6-astra-pro-fast"]["dimensions"]["price"]["service_tier_multiplier"],
            2.0,
        )
        self.assertEqual(
            rows["openai/gpt-6-astra-pro-flex"]["dimensions"]["price"]["service_tier_multiplier"],
            0.5,
        )
        self.assertEqual(
            rows["gateway/provider-only-astra"]["status"],
            "intentional_exclusion",
        )
        for model_id in ("openai/gpt-6-astra-turbo", "openai/gpt-6-astra-2"):
            row = rows[model_id]
            with self.subTest(model_id=model_id):
                self.assertEqual(row["status"], "missing")
                self.assertIsNone(row["contract_model_id"])
                self.assertEqual(row["dimensions"]["contract"]["status"], "missing")
                self.assertEqual(row["dimensions"]["provider_eligibility"]["status"], "missing")
                self.assertEqual(row["dimensions"]["category_projection"]["status"], "missing")
                self.assertEqual(row["dimensions"]["price"]["status"], "absent")
                self.assertEqual(row["dimensions"]["docs"]["status"], "missing")

        self.assertEqual(
            comparison["summary"]["status_counts"],
            {
                "dated_snapshot": 1,
                "declared_inheritance": 5,
                "exact": 1,
                "intentional_exclusion": 1,
                "missing": 2,
            },
        )
        self.assertFalse(report["blocking"])
        self.assertEqual(coverage_exit_code(report), 0)
        self.assertIn("not evidence", report["claim_boundary"])

    def test_requirements_separate_blockers_recommendations_and_optional_discovery(self) -> None:
        report = build_model_contract_coverage(
            _inventory(("vendor/optional-new", "vendor/recommended-new", "vendor/required-new")),
            required_models=("vendor/required-new",),
            recommended_models=("vendor/recommended-new",),
        )
        rows = {row["requested_model"]: row for row in report["comparison"]["models"]}
        self.assertEqual(rows["vendor/required-new"]["actionability"], "required_missing")
        self.assertEqual(rows["vendor/recommended-new"]["actionability"], "recommended_missing")
        self.assertEqual(rows["vendor/optional-new"]["actionability"], "optional_discovery")
        summary = report["comparison"]["summary"]
        self.assertEqual(summary["required_missing"], 1)
        self.assertEqual(summary["recommended_missing"], 1)
        self.assertEqual(summary["optional_discovery"], 1)
        self.assertTrue(report["blocking"])
        self.assertEqual(coverage_exit_code(report), 1)

    def test_cold_and_unavailable_inventories_stay_distinct_from_empty_observed(self) -> None:
        reports = {
            status: build_model_contract_coverage(_inventory((), status=status))
            for status in ("observed", "cold", "unavailable")
        }
        self.assertEqual(
            {status: report["comparison"]["inventory"]["status"] for status, report in reports.items()},
            {"observed": "observed", "cold": "cold", "unavailable": "unavailable"},
        )
        self.assertEqual(reports["observed"]["comparison"]["summary"]["outcome"], "covered")
        self.assertEqual(reports["cold"]["comparison"]["summary"]["outcome"], "cold_inventory")
        self.assertEqual(
            reports["unavailable"]["comparison"]["summary"]["outcome"],
            "unavailable_inventory",
        )

    def test_existing_observed_inventory_preserves_per_id_evidence_without_timestamps(self) -> None:
        inventory = {
            "schema_version": "model_inventory/v1",
            "observed_at": "2026-09-05T00:00:00Z",
            "available_models": [
                {
                    "provider": "openai",
                    "model_id": "gpt-6-astra-fast",
                    "variants": ["xhigh"],
                    "family": "gpt",
                }
            ],
            "model_discovery": {
                "observations": [
                    {
                        "source": "codex",
                        "provider": "openai",
                        "model_id": "openai/gpt-6-astra-pro-flex",
                        "variant": "",
                        "timestamp": "2026-09-04T12:34:56Z",
                        "status": "confirmed_active",
                    }
                ]
            },
        }

        report = build_model_contract_coverage(inventory)

        rows = {row["requested_model"]: row for row in report["comparison"]["models"]}
        self.assertEqual(set(rows), {"openai/gpt-6-astra-fast", "openai/gpt-6-astra-pro-flex"})
        self.assertEqual(
            rows["openai/gpt-6-astra-fast"]["inventory_evidence"]["records"],
            [{"source": "available_models", "status": "configured"}],
        )
        self.assertEqual(
            rows["openai/gpt-6-astra-pro-flex"]["inventory_evidence"]["records"],
            [{"source": "codex", "status": "confirmed_active"}],
        )
        self.assertNotIn("timestamp", str(report["comparison"]))

    def test_malformed_or_missing_inventory_structure_is_rejected(self) -> None:
        invalid = (
            {},
            {"models": "gpt-6-astra"},
            {"models": [42]},
            {"models": [{}]},
            {"models": [{"model_id": 42}]},
            {"models": [{"model_id": "gpt-6-astra", "provider": None}]},
            {"models": [{"model_id": "gpt-6-astra", "source": None}]},
            {"models": [{"model_id": "gpt-6-astra", "status": None}]},
            {"available_models": {}},
            {"available_models": [{"provider": "openai"}]},
            {"available_models": [{"model_id": "gpt-6-astra", "provider": None}]},
            {"model_discovery": {"observations": {}}},
            {"model_discovery": {"observations": [{}]}},
            {
                "model_discovery": {
                    "observations": [{"model_id": "gpt-6-astra", "provider": None}]
                }
            },
            {
                "model_discovery": {
                    "observations": [{"model_id": "gpt-6-astra", "source": None}]
                }
            },
            {
                "model_discovery": {
                    "observations": [{"model_id": "gpt-6-astra", "status": None}]
                }
            },
            {"models": [], "provenance": None},
            {"models": [], "provenance": {"source": None}},
            {"models": [], "provenance": {"digest": None}},
            {"models": [], "source": None},
            {"models": [], "digest": None},
            {"models": [], "schema_version": None},
        )
        for inventory in invalid:
            with self.subTest(inventory=inventory):
                with self.assertRaisesRegex(ValueError, "inventory"):
                    build_model_contract_coverage(inventory)

    def test_case_variants_merge_without_losing_supplied_identities(self) -> None:
        inventory = {
            "schema_version": "model_inventory/v1",
            "models": ["OpenAI/GPT-6-ASTRA-FAST"],
            "available_models": [
                {"provider": "openai", "model_id": "gpt-6-astra-fast"}
            ],
        }
        first = build_model_contract_coverage(
            inventory,
            required_models=("OPENAI/gpt-6-astra-fast",),
        )
        second = build_model_contract_coverage(
            {
                **inventory,
                "models": list(reversed(inventory["models"])),
                "available_models": list(reversed(inventory["available_models"])),
            },
            required_models=("OPENAI/gpt-6-astra-fast",),
        )

        self.assertEqual(first, second)
        rows = first["comparison"]["models"]
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["status"], "declared_inheritance")
        self.assertEqual(
            row["inventory_evidence"]["identities"],
            ["OpenAI/GPT-6-ASTRA-FAST", "openai/gpt-6-astra-fast"],
        )
        self.assertEqual(
            row["inventory_evidence"]["records"],
            [
                {"source": "available_models", "status": "configured"},
                {"source": "supplied_models", "status": "supplied"},
            ],
        )

    def test_comparison_and_digest_are_stable_without_timestamps(self) -> None:
        first_inventory = _inventory(tuple(reversed(_ASTRA_FORMS)))
        second_inventory = _inventory(_ASTRA_FORMS)
        first_inventory["observed_at"] = "2026-09-05T00:00:00Z"
        second_inventory["observed_at"] = "2099-01-01T00:00:00Z"

        first = build_model_contract_coverage(first_inventory)
        second = build_model_contract_coverage(second_inventory)

        self.assertEqual(first, second)
        self.assertEqual(first["comparison_digest"], second["comparison_digest"])
        self.assertNotIn("observed_at", str(first["comparison"]))
        inventory = first["comparison"]["inventory"]
        self.assertEqual(inventory["source"], "host_catalog_fixture")
        self.assertEqual(inventory["supplied_digest"], "host-supplied-digest-01")
        self.assertEqual(len(inventory["digest"]), 64)
        for row in first["comparison"]["models"]:
            self.assertEqual(row["inventory_evidence"]["digest"], inventory["digest"])
            self.assertEqual(row["inventory_evidence"]["source"], inventory["source"])


class CoverageCliTests(unittest.TestCase):
    def test_model_contract_audit_reads_local_json_and_is_repeatable(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            inventory_path = root / "inventory.json"
            inventory_path.write_text(
                json.dumps(_inventory((*_ASTRA_FORMS, "openai/gpt-6-astra-turbo"))),
                encoding="utf-8",
            )
            command = [
                "coding",
                "model-contract-audit",
                "--inventory",
                str(inventory_path),
                "--required-model",
                "openai/gpt-6-astra-pro-flex",
                "--json",
            ]

            first = run_cli(command)
            second = run_cli(command)

        self.assertEqual(first, second)
        status, stdout, stderr = first
        self.assertEqual(status, 0, stderr)
        self.assertEqual(stderr, "")
        report = json.loads(stdout)
        self.assertEqual(report["schema_version"], MODEL_CONTRACT_COVERAGE_SCHEMA_VERSION)
        self.assertFalse(report["blocking"])
        rows = {row["requested_model"]: row for row in report["comparison"]["models"]}
        self.assertEqual(rows["openai/gpt-6-astra-pro-flex"]["status"], "declared_inheritance")
        self.assertEqual(rows["openai/gpt-6-astra-turbo"]["actionability"], "optional_discovery")

    def test_model_contract_audit_accepts_stdin_and_required_gaps_block(self) -> None:
        raw = json.dumps(_inventory(("openai/gpt-6-astra",)))
        status, stdout, stderr = run_cli(
            [
                "coding",
                "model-contract-audit",
                "--inventory",
                "-",
                "--required-model",
                "vendor/required-new",
                "--recommended-model",
                "vendor/recommended-new",
                "--intentional-exclusion",
                "vendor/provider-only",
                "--json",
            ],
            stdin_text=raw,
        )

        self.assertEqual(status, 1)
        self.assertEqual(stderr, "")
        report = json.loads(stdout)
        rows = {row["requested_model"]: row for row in report["comparison"]["models"]}
        self.assertEqual(rows["vendor/required-new"]["actionability"], "required_missing")
        self.assertEqual(rows["vendor/recommended-new"]["actionability"], "recommended_missing")
        self.assertEqual(rows["vendor/provider-only"]["status"], "intentional_exclusion")

    def test_model_contract_audit_rejects_unbounded_or_non_object_json(self) -> None:
        too_large = "{" + (" " * 1_048_576) + "}"
        status, stdout, stderr = run_cli(
            ["coding", "model-contract-audit", "--inventory", "-", "--json"],
            stdin_text=too_large,
        )
        self.assertNotEqual(status, 0)
        self.assertEqual(stdout, "")
        self.assertIn("exceeds 1048576 bytes", stderr)

        status, stdout, stderr = run_cli(
            ["coding", "model-contract-audit", "--inventory", "-", "--json"],
            stdin_text="[]",
        )
        self.assertNotEqual(status, 0)
        self.assertEqual(stdout, "")
        self.assertIn("must contain a JSON object", stderr)

    def test_model_contract_audit_rejects_null_duplicate_and_nonfinite_json(self) -> None:
        malformed = (
            '{"models":null}',
            '{"available_models":null}',
            '{"model_discovery":null}',
            '{"models":[],"models":["gpt-6-astra-turbo"]}',
            '{"models":[],"unexpected":NaN}',
            '{"models":[],"unexpected":1e999}',
            '{"models":[{"model_id":"gpt-6-astra","source":-1e999}]}',
            '{"models":[{"model_id":"gpt-6-astra","provider":null}]}',
            '{"models":[{"model_id":"gpt-6-astra","source":null}]}',
            '{"models":[{"model_id":"gpt-6-astra","status":null}]}',
        )
        for raw in malformed:
            with self.subTest(raw=raw):
                status, stdout, stderr = run_cli(
                    ["coding", "model-contract-audit", "--inventory", "-", "--json"],
                    stdin_text=raw,
                )
                self.assertNotEqual(status, 0)
                self.assertEqual(stdout, "")
                self.assertTrue(stderr)

    def test_model_contract_audit_rejects_sensitive_supplied_digest_without_echo(self) -> None:
        sensitive = "sk-example-sensitive-value-1234567890"
        status, stdout, stderr = run_cli(
            ["coding", "model-contract-audit", "--inventory", "-", "--json"],
            stdin_text=json.dumps(
                {
                    "models": [],
                    "provenance": {"source": "fixture", "digest": sensitive},
                }
            ),
        )

        self.assertNotEqual(status, 0)
        self.assertEqual(stdout, "")
        self.assertNotIn(sensitive, stderr)
        self.assertIn("inventory_digest", stderr)


if __name__ == "__main__":
    unittest.main()
