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

from omh.coding.model_contracts import contract_effort_option
from omh.plugin_bundle.omh.hermes_delegation import MODEL_PROVIDER_ROUTES_SCHEMA_VERSION
from omh.plugin_bundle.omh.model_chain_picker import (
    MODEL_EFFORT_OPTIONS_SCHEMA_VERSION,
    effort_option_resolver,
    load_model_effort_options,
    parse_model_effort_options,
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
        self.assertIsNotNone(option)
        assert option is not None
        self.assertEqual(option["efforts"], ("none", "low", "medium", "high", "xhigh", "max"))
        self.assertEqual(option["source"], "contract")
        self.assertEqual(option["model_id"], "claude-haiku-5-5")
        self.assertEqual(option["provenance"], "exact")
        self.assertTrue(option["thinking_disable"])
        # And the R6 example: xhigh + reaches max.
        self.assertIn("max", option["efforts"])

    def test_always_thinking_models_exclude_none(self) -> None:
        for model_id in ("claude-opus-5-5", "claude-sonnet-5-5", "kimi-k3.1-pro", "gpt-6-astra"):
            with self.subTest(model_id=model_id):
                option = contract_effort_option(model_id)
                assert option is not None
                self.assertNotIn("none", option["efforts"])
                self.assertFalse(option["thinking_disable"])

    def test_kimi_low_high_max_only(self) -> None:
        option = contract_effort_option("kimi-k3.1-pro")
        assert option is not None
        self.assertEqual(option["efforts"], ("low", "high", "max"))

    def test_deepseek_mapping_aliases_are_not_independent_rungs(self) -> None:
        option = contract_effort_option("deepseek-flash")
        assert option is not None
        self.assertEqual(option["efforts"], ("none", "low", "high", "max"))
        self.assertEqual(option["model_id"], "deepseek-v4.1-flash")
        self.assertEqual(option["provenance"], "declared_inheritance")
        for alias in ("medium", "xhigh", "minimal", "ultra"):
            self.assertNotIn(alias, option["efforts"])

    def test_declared_and_dated_snapshot_aliases_resolve(self) -> None:
        opus = contract_effort_option("anthropic.claude-opus-5-5")
        assert opus is not None
        self.assertEqual(opus["model_id"], "claude-opus-5-5")
        self.assertEqual(opus["provenance"], "declared_inheritance")
        snapshot = contract_effort_option("gpt-6.1-sol-2026-10-01")
        assert snapshot is not None
        self.assertEqual(snapshot["model_id"], "gpt-6.1-sol")
        self.assertEqual(snapshot["provenance"], "dated_snapshot")
        self.assertNotIn("none", snapshot["efforts"])

    def test_models_without_a_contract_are_unknown_not_wide_open(self) -> None:
        for model_id in ("glm-5.3", "glm-5.3-flash", "claude-fable-5-1", "gpt-5.6-terra", "custom:mine", ""):
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


class EffortResolverTests(unittest.TestCase):
    def test_user_override_replaces_the_built_in_ladder(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_efforts(root, {"claude-haiku-5-5": {"efforts": ["low", "high"]}})
            resolve, status = effort_option_resolver(root, contract_option=contract_effort_option)
            option = resolve("claude-haiku-5-5")
        self.assertEqual(status, "applied")
        assert option is not None
        self.assertEqual(option["efforts"], ("low", "high"))
        self.assertEqual(option["source"], "user")
        self.assertFalse(option["thinking_disable"])
        self.assertEqual(option["override_key"], "claude-haiku-5-5")

    def test_a_custom_model_and_an_empty_override_are_configured(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_efforts(root, {"my-custom": {"efforts": ["none", "max"]}, "other": {"efforts": []}})
            resolve, _status = effort_option_resolver(root, contract_option=contract_effort_option)
            custom = resolve("my-custom")
            empty = resolve("other")
        assert custom is not None and empty is not None
        self.assertEqual(custom["efforts"], ("none", "max"))
        self.assertTrue(custom["thinking_disable"])
        self.assertEqual(empty["efforts"], ())
        self.assertEqual(empty["source"], "user")

    def test_unknown_and_contractless_models_stay_unconfigured(self) -> None:
        with TemporaryDirectory() as tmp:
            resolve, _status = effort_option_resolver(Path(tmp), contract_option=contract_effort_option)
            self.assertIsNone(resolve("glm-5.3"))
            self.assertIsNone(resolve("totally-unknown"))
            self.assertIsNone(resolve(""))

    def test_exact_wire_id_is_checked_before_the_alias(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_routes(root, {"work": ("openrouter", "claude-haiku-5-5")})
            _write_efforts(root, {"work": {"efforts": ["low"]}, "claude-haiku-5-5": {"efforts": ["high"]}})
            resolve, _status = effort_option_resolver(root, contract_option=contract_effort_option)
            option = resolve("work")
        assert option is not None
        # The user named both the alias and the exact wire model; the wire
        # model is what actually runs, so its entry wins.
        self.assertEqual(option["efforts"], ("high",))
        self.assertEqual(option["override_key"], "claude-haiku-5-5")

    def test_alias_override_applies_when_the_wire_model_has_none(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_routes(root, {"work": ("openrouter", "claude-haiku-5-5")})
            _write_efforts(root, {"work": {"efforts": ["low", "high"]}})
            resolve, _status = effort_option_resolver(root, contract_option=contract_effort_option)
            option = resolve("work")
        assert option is not None
        self.assertEqual(option["efforts"], ("low", "high"))
        self.assertEqual(option["override_key"], "work")

    def test_a_route_uses_the_wire_models_built_in_ladder(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_routes(root, {"work": ("openrouter", "claude-haiku-5-5")})
            resolve, _status = effort_option_resolver(root, contract_option=contract_effort_option)
            option = resolve("work")
        assert option is not None
        self.assertEqual(option["source"], "contract")
        self.assertEqual(option["model_id"], "claude-haiku-5-5")
        self.assertIn("none", option["efforts"])

    def test_a_provider_qualified_wire_id_is_not_merged_with_a_bare_override(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_routes(root, {"work": ("openrouter", "openrouter/claude-haiku-5-5")})
            _write_efforts(root, {"claude-haiku-5-5": {"efforts": ["low", "max"]}})
            resolve, _status = effort_option_resolver(root, contract_option=contract_effort_option)
            option = resolve("work")
        assert option is not None
        # The user named the bare contract id; the routed wire id is a
        # different exact key, so the built-in contract applies instead of
        # silently merging two unequal routes.
        self.assertEqual(option["source"], "contract")
        self.assertEqual(option["override_key"], "")
        self.assertIn("medium", option["efforts"])

    def test_an_invalid_override_document_is_reported_and_does_not_widen_custom_models(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "routing" / "model-efforts.json"
            path.parent.mkdir(parents=True)
            path.write_text("[]", encoding="utf-8")
            resolve, status = effort_option_resolver(root, contract_option=contract_effort_option)
            self.assertTrue(status.startswith("invalid:"), status)
            self.assertIsNone(resolve("my-custom"))
            # Built-in truth still applies to a known model; the status the
            # picker paints is what keeps that fallback visible.
            haiku = resolve("claude-haiku-5-5")
        assert haiku is not None
        self.assertEqual(haiku["source"], "contract")


if __name__ == "__main__":
    unittest.main()
