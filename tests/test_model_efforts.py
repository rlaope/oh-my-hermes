"""Per-model selectable reasoning efforts: built-in truth and user overrides.

The picker's stepping is only as honest as the ladder it is handed. These
tests pin the resolver's contract-backed ladders (including declared aliases
and dated snapshots), the documented no-thinking capability, the strict
`model_efforts` document, and the wire-id-before-alias precedence.
"""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from omh.coding.model_contracts import MODEL_CONTRACTS, contract_effort_option
from omh.plugin_bundle.omh.hermes_delegation import MODEL_PROVIDER_ROUTES_SCHEMA_VERSION, load_model_provider_routes
from omh.plugin_bundle.omh.model_chain_picker import (
    EFFORT_VOCABULARY,
    MODEL_EFFORT_OPTIONS_SCHEMA_VERSION,
    effort_option_resolver,
    load_model_effort_options,
    parse_model_effort_options,
    picker_rows,
)


def _write_efforts(root: Path, models: dict[str, object]) -> Path:
    path = root / "routing" / "model-efforts.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"schema_version": MODEL_EFFORT_OPTIONS_SCHEMA_VERSION, "models": models}),
        encoding="utf-8",
    )
    return path


def _write_routes(root: Path, models: dict[str, tuple[str, str]]) -> Path:
    path = root / "routing" / "model-providers.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": MODEL_PROVIDER_ROUTES_SCHEMA_VERSION,
                "models": {
                    alias: {"provider": provider, "model": model}
                    for alias, (provider, model) in models.items()
                },
            }
        ),
        encoding="utf-8",
    )
    return path


class ContractEffortOptionTests(unittest.TestCase):
    def test_haiku_exposes_its_documented_ladder_and_the_disable_rung(self) -> None:
        option = contract_effort_option("claude-haiku-5-5")
        self.assertEqual(option, {"efforts": ("none", "low", "medium", "high", "xhigh", "max"), "source": "contract"})

    def test_always_thinking_models_exclude_none(self) -> None:
        for model_id in ("claude-opus-5-5", "claude-sonnet-5-5", "kimi-k3.1-pro", "gpt-6-astra"):
            with self.subTest(model_id=model_id):
                self.assertNotIn("none", contract_effort_option(model_id)["efforts"])

    def test_kimi_low_high_max_only(self) -> None:
        self.assertEqual(contract_effort_option("kimi-k3.1-pro")["efforts"], ("low", "high", "max"))

    def test_fable_glm_flash_and_grok_heads_carry_their_documented_ladders(self) -> None:
        # Read from the vendor pages each contract cites: Fable 5.1 takes all
        # five Claude levels, GLM-5.3-Flash GLM-5.3's three, and Grok 4.7
        # xAI's four. None of them can turn reasoning off, so `none` is absent.
        for model_id, efforts in (
            ("claude-fable-5-1", ("low", "medium", "high", "xhigh", "max")),
            ("glm-5.3-flash", ("low", "high", "max")),
            ("grok-4.7", ("low", "medium", "high", "xhigh")),
        ):
            with self.subTest(model_id=model_id):
                self.assertEqual(contract_effort_option(model_id), {"efforts": efforts, "source": "contract"})

    def test_deepseek_mapping_aliases_are_not_independent_rungs(self) -> None:
        self.assertEqual(contract_effort_option("deepseek-flash")["efforts"], ("none", "low", "high", "max"))

    def test_declared_and_dated_snapshot_aliases_resolve_to_their_contract(self) -> None:
        self.assertEqual(
            contract_effort_option("anthropic.claude-opus-5-5")["efforts"],
            contract_effort_option("claude-opus-5-5")["efforts"],
        )
        self.assertEqual(
            contract_effort_option("gpt-6.1-sol-2026-10-01")["efforts"],
            contract_effort_option("gpt-6.1-sol")["efforts"],
        )

    def test_every_contract_rung_is_in_the_picker_vocabulary(self) -> None:
        for model_id, contract in MODEL_CONTRACTS.items():
            for rung in contract.get("reasoning_efforts") or ():
                with self.subTest(model_id=model_id, rung=rung):
                    self.assertIn(rung, EFFORT_VOCABULARY)

    def test_none_is_offered_exactly_where_the_contract_allows_turning_thinking_off(self) -> None:
        # The disable set in `contract_effort_option` is a hand-kept list. A new
        # contract that disagrees with its own `unsupported_efforts` lands here
        # and forces a decision about which of the two is right.
        for model_id, contract in MODEL_CONTRACTS.items():
            if not contract.get("reasoning_efforts"):
                continue
            with self.subTest(model_id=model_id):
                self.assertEqual(
                    "none" in contract_effort_option(model_id)["efforts"],
                    "off" not in (contract.get("unsupported_efforts") or ()),
                )

    def test_a_rung_outside_the_vocabulary_is_dropped_without_raising(self) -> None:
        contract = {**MODEL_CONTRACTS["gpt-6-luna"], "reasoning_efforts": ["low", "ultra", "high"]}
        with patch.dict(MODEL_CONTRACTS, {"gpt-6-luna": contract}):
            self.assertEqual(contract_effort_option("gpt-6-luna")["efforts"], ("low", "high"))
            with TemporaryDirectory() as tmp:
                payload = picker_rows(Path(tmp) / "omh", hermes_home=Path(tmp) / "hermes", contract_option=contract_effort_option)
            luna = next(row for row in payload["models"] if row["alias"] == "gpt-6-luna")
            self.assertEqual(luna["efforts"], ["low", "high"])
        # Nothing left is no authority, not the user's "turn the keys off".
        contract = {**MODEL_CONTRACTS["gpt-6-luna"], "reasoning_efforts": ["ultra"]}
        with patch.dict(MODEL_CONTRACTS, {"gpt-6-luna": contract}):
            self.assertIsNone(contract_effort_option("gpt-6-luna"))

    def test_models_without_a_contract_are_unknown_not_wide_open(self) -> None:
        # GLM-5.3 stays here until its speed tiers have declared rows (see the
        # GLM-5.3-Flash contract); Grok Build 0.1 documents no effort parameter.
        for model_id in ("glm-5.3", "grok-build-0.1", "gpt-5.6-terra", "custom:mine", ""):
            with self.subTest(model_id=model_id):
                self.assertIsNone(contract_effort_option(model_id))


class EffortDocumentTests(unittest.TestCase):
    def test_absent_and_valid_documents(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            overrides, status = load_model_effort_options(root)
            self.assertEqual((overrides, status), ({}, "absent"))
            _write_efforts(root, {"claude-haiku-5-5": {"efforts": ["high", "none", "low"]}})
            overrides, status = load_model_effort_options(root)
        self.assertEqual(status, "applied")
        # Deterministic vocabulary order, regardless of file order.
        self.assertEqual(overrides["claude-haiku-5-5"], ("none", "low", "high"))

    def test_an_empty_list_is_a_configured_no_knob(self) -> None:
        overrides, status = parse_model_effort_options(
            {
                "schema_version": MODEL_EFFORT_OPTIONS_SCHEMA_VERSION,
                "models": {"my-custom-model": {"efforts": []}},
            }
        )
        self.assertEqual(status, "applied")
        self.assertEqual(overrides, {"my-custom-model": ()})

    def test_invalid_documents_are_rejected_whole(self) -> None:
        base = {"schema_version": MODEL_EFFORT_OPTIONS_SCHEMA_VERSION, "models": {}}
        cases = {
            "not an object": [],
            "wrong schema": {**base, "schema_version": "model_efforts/v1"},
            "unknown top field": {**base, "extra": 1},
            "missing models": {"schema_version": MODEL_EFFORT_OPTIONS_SCHEMA_VERSION},
            "models not object": {**base, "models": []},
            "bad model token": {**base, "models": {"bad model!": {"efforts": ["low"]}}},
            "entry not object": {**base, "models": {"m": ["low"]}},
            "unknown entry field": {**base, "models": {"m": {"efforts": ["low"], "source": "x"}}},
            "efforts not list": {**base, "models": {"m": {"efforts": "low"}}},
            "empty element": {**base, "models": {"m": {"efforts": [""]}}},
            "non-string": {**base, "models": {"m": {"efforts": [1]}}},
            "off spelling": {**base, "models": {"m": {"efforts": ["off"]}}},
            "auto is not a level": {**base, "models": {"m": {"efforts": ["auto"]}}},
            "outside vocabulary": {**base, "models": {"m": {"efforts": ["ultra"]}}},
            "uppercase": {**base, "models": {"m": {"efforts": ["LOW"]}}},
            "padded": {**base, "models": {"m": {"efforts": [" low "]}}},
            "duplicate rung": {**base, "models": {"m": {"efforts": ["low", "low"]}}},
            "duplicate model spelling": {
                **base,
                "models": {"Model": {"efforts": ["low"]}, "model": {"efforts": ["high"]}},
            },
        }
        for name, document in cases.items():
            with self.subTest(name=name):
                overrides, status = parse_model_effort_options(document)
                self.assertEqual(overrides, {})
                self.assertTrue(status.startswith("invalid:"), status)

    def test_the_old_off_spelling_is_told_what_to_write(self) -> None:
        document = {"schema_version": MODEL_EFFORT_OPTIONS_SCHEMA_VERSION, "models": {"m": {"efforts": ["off"]}}}
        self.assertIn("write 'none'", parse_model_effort_options(document)[1])

    def test_duplicate_json_keys_and_unreadable_text_are_invalid(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "routing" / "model-efforts.json"
            path.parent.mkdir(parents=True)
            path.write_text('{"schema_version": "' + MODEL_EFFORT_OPTIONS_SCHEMA_VERSION + '", "models": {}}', encoding="utf-8")
            overrides, status = load_model_effort_options(root)
            self.assertEqual((overrides, status), ({}, "applied"))
            path.write_text("{", encoding="utf-8")
            self.assertEqual(load_model_effort_options(root), ({}, "invalid: unreadable JSON"))
            path.write_text(
                '{"schema_version": "' + MODEL_EFFORT_OPTIONS_SCHEMA_VERSION
                + '", "models": {"m": {"efforts": ["low"]}, "m": {"efforts": ["high"]}}}',
                encoding="utf-8",
            )
            self.assertEqual(load_model_effort_options(root), ({}, "invalid: unreadable JSON"))


class UnreadableFileTests(unittest.TestCase):
    def test_a_file_that_cannot_be_read_is_invalid_not_a_crash(self) -> None:
        for name, loader in (
            ("model-efforts.json", load_model_effort_options),
            ("model-providers.json", load_model_provider_routes),
        ):
            with self.subTest(name=name), TemporaryDirectory() as tmp:
                root = Path(tmp)
                path = root / "routing" / name
                path.parent.mkdir(parents=True)
                path.write_text("[" * 200_000, encoding="utf-8")  # past the parser's nesting limit
                self.assertEqual(loader(root), ({}, "invalid: unreadable JSON"))
                path.unlink()
                path.mkdir()  # an OSError on every platform, unlike a mode bit
                self.assertEqual(loader(root), ({}, "invalid: unreadable JSON"))


class EffortResolverTests(unittest.TestCase):
    def _option(self, root: Path, alias: str):
        resolve, _status = effort_option_resolver(root, contract_effort_option)
        return resolve(alias)

    def test_user_entry_replaces_the_built_in_ladder(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_efforts(root, {"claude-haiku-5-5": {"efforts": ["low", "high"]}})
            self.assertEqual(self._option(root, "claude-haiku-5-5"), {"efforts": ("low", "high"), "source": "user"})

    def test_a_custom_model_and_an_empty_entry_are_both_known(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_efforts(root, {"my-custom": {"efforts": ["none", "max"]}, "other": {"efforts": []}})
            self.assertEqual(self._option(root, "my-custom"), {"efforts": ("none", "max"), "source": "user"})
            self.assertEqual(self._option(root, "other"), {"efforts": (), "source": "user"})

    def test_a_key_matches_whatever_its_case(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_efforts(root, {"My-Custom": {"efforts": ["low"]}})
            self.assertEqual(self._option(root, "my-custom"), {"efforts": ("low",), "source": "user"})
            self.assertEqual(self._option(root, "MY-CUSTOM"), {"efforts": ("low",), "source": "user"})

    def test_a_model_nobody_names_resolves_to_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            for alias in ("glm-5.3", "totally-unknown", ""):
                with self.subTest(alias=alias):
                    self.assertIsNone(self._option(Path(tmp), alias))

    def test_exact_wire_id_is_checked_before_the_alias(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_routes(root, {"work": ("openrouter", "claude-haiku-5-5")})
            _write_efforts(root, {"work": {"efforts": ["low"]}, "claude-haiku-5-5": {"efforts": ["high"]}})
            # The wire model is what actually runs, so its entry wins.
            self.assertEqual(self._option(root, "work")["efforts"], ("high",))

    def test_alias_entry_applies_when_the_wire_model_has_none(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_routes(root, {"work": ("openrouter", "claude-haiku-5-5")})
            _write_efforts(root, {"work": {"efforts": ["low", "high"]}})
            self.assertEqual(self._option(root, "work")["efforts"], ("low", "high"))

    def test_a_user_entry_at_either_key_beats_any_contract(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_routes(root, {"claude-opus-5-5": ("openrouter", "my-wire")})
            _write_efforts(root, {"my-wire": {"efforts": ["low"]}})
            self.assertEqual(self._option(root, "claude-opus-5-5"), {"efforts": ("low",), "source": "user"})

    def test_a_route_uses_the_wire_models_built_in_ladder(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_routes(root, {"work": ("openrouter", "claude-haiku-5-5")})
            self.assertEqual(self._option(root, "work"), contract_effort_option("claude-haiku-5-5"))

    def test_a_provider_qualified_wire_id_is_not_merged_with_a_bare_entry(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_routes(root, {"work": ("openrouter", "openrouter/claude-haiku-5-5")})
            _write_efforts(root, {"claude-haiku-5-5": {"efforts": ["low", "max"]}})
            # A different exact key, so the contract applies instead of the entry.
            self.assertEqual(self._option(root, "work"), contract_effort_option("claude-haiku-5-5"))

    def test_an_entry_under_a_pointers_target_does_not_reach_the_pointer(self) -> None:
        # The key is the chain alias or wire id, not the contract id. The docs
        # say so, because the status reads `applied` while the row is untouched.
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_efforts(root, {"deepseek-v4.1-flash": {"efforts": ["low"]}})
            resolve, status = effort_option_resolver(root, contract_effort_option)
            self.assertEqual(status, "applied")
            self.assertEqual(resolve("deepseek-flash"), contract_effort_option("deepseek-flash"))

    def test_an_invalid_document_is_reported_and_built_in_ladders_keep_applying(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "routing" / "model-efforts.json"
            path.parent.mkdir(parents=True)
            path.write_text("[]", encoding="utf-8")
            resolve, status = effort_option_resolver(root, contract_effort_option)
            self.assertTrue(status.startswith("invalid:"), status)
            self.assertIsNone(resolve("my-custom"))
            self.assertEqual(resolve("claude-haiku-5-5"), contract_effort_option("claude-haiku-5-5"))


if __name__ == "__main__":
    unittest.main()
