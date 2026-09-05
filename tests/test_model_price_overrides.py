"""The user's own price document decides what a token costs.

Prices differ per user and drift: a gateway marks up, an enterprise contract
is not the list price, a free tier bills nothing, and vendors reprice. The
shipped table is a ballpark, so these tests pin the rule that the operator's
own document wins where it speaks, that an invalid document is ignored whole
rather than half-applied, and that a model OMH never priced can be priced
here — which is the only way a user reaches one today.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from omh.plugin_bundle.omh.hermes_delegation import (
    MODEL_PRICE_OVERRIDES_SCHEMA_VERSION,
    _approximate_cost_usd,
    load_model_price_overrides,
    model_price_overrides_path,
    parse_model_price_overrides,
)


def _document(models: dict[str, object]) -> dict[str, object]:
    return {"schema_version": MODEL_PRICE_OVERRIDES_SCHEMA_VERSION, "models": models}


class ParseTests(unittest.TestCase):
    def test_a_valid_document_applies(self) -> None:
        overrides, status = parse_model_price_overrides(
            _document({"claude-fable-5-1": {"input_per_mtok": 8.0, "output_per_mtok": 40.0}})
        )
        self.assertEqual(status, "applied")
        self.assertEqual(overrides, {"claude-fable-5-1": (8.0, 40.0, None)})

    def test_the_cache_ratio_is_optional_and_carried_when_given(self) -> None:
        overrides, status = parse_model_price_overrides(
            _document({
                "m": {"input_per_mtok": 1.0, "output_per_mtok": 2.0, "cache_read_ratio": 0.025}
            })
        )
        self.assertEqual(status, "applied")
        self.assertEqual(overrides, {"m": (1.0, 2.0, 0.025)})

    def test_a_model_name_is_folded_so_lookups_match(self) -> None:
        overrides, _ = parse_model_price_overrides(
            _document({"Claude-Fable-5-1": {"input_per_mtok": 1.0, "output_per_mtok": 2.0}})
        )
        self.assertIn("claude-fable-5-1", overrides)

    def test_every_invalid_document_is_rejected_whole(self) -> None:
        # Atomic, matching the sibling documents: half a price table is worse
        # than none, because the half that applied is invisible.
        cases = {
            "not an object": [],
            "wrong schema": {"schema_version": "nope", "models": {}},
            "unsupported field": {
                "schema_version": MODEL_PRICE_OVERRIDES_SCHEMA_VERSION,
                "models": {},
                "extra": 1,
            },
            "models not an object": _document([]),  # type: ignore[arg-type]
            "entry not an object": _document({"m": 1.0}),
            "unknown entry field": _document({"m": {"input_per_mtok": 1.0, "output_per_mtok": 2.0, "rate": 3}}),
            "missing output": _document({"m": {"input_per_mtok": 1.0}}),
            "boolean rate": _document({"m": {"input_per_mtok": True, "output_per_mtok": 2.0}}),
            "negative rate": _document({"m": {"input_per_mtok": -1.0, "output_per_mtok": 2.0}}),
            "ratio above one": _document({
                "m": {"input_per_mtok": 1.0, "output_per_mtok": 2.0, "cache_read_ratio": 1.5}
            }),
            "path-shaped name": _document({"../m": {"input_per_mtok": 1.0, "output_per_mtok": 2.0}}),
        }
        for label, raw in cases.items():
            with self.subTest(case=label):
                overrides, status = parse_model_price_overrides(raw)
                self.assertEqual(overrides, {})
                self.assertTrue(status.startswith("invalid: "), status)


class LoadTests(unittest.TestCase):
    def test_an_absent_document_is_absent_not_invalid(self) -> None:
        with TemporaryDirectory() as tmp:
            overrides, status = load_model_price_overrides(Path(tmp))
            self.assertEqual((overrides, status), ({}, "absent"))

    def test_a_written_document_round_trips(self) -> None:
        with TemporaryDirectory() as tmp:
            path = model_price_overrides_path(Path(tmp))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(_document({"m": {"input_per_mtok": 3.0, "output_per_mtok": 6.0}})),
                encoding="utf-8",
            )
            overrides, status = load_model_price_overrides(Path(tmp))
            self.assertEqual(status, "applied")
            self.assertEqual(overrides, {"m": (3.0, 6.0, None)})

    def test_unreadable_json_is_invalid_not_a_crash(self) -> None:
        with TemporaryDirectory() as tmp:
            path = model_price_overrides_path(Path(tmp))
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{not json", encoding="utf-8")
            overrides, status = load_model_price_overrides(Path(tmp))
            self.assertEqual(overrides, {})
            self.assertEqual(status, "invalid: unreadable JSON")


class PricingTests(unittest.TestCase):
    def test_declared_astra_tiers_inherit_base_rates_without_a_pro_multiplier(self) -> None:
        expected = {
            "gpt-6-astra": 60.0,
            "gpt-6-astra-pro": 60.0,
            "gpt-6-astra-fast": 120.0,
            "gpt-6-astra-pro-fast": 120.0,
            "gpt-6-astra-flex": 30.0,
            "gpt-6-astra-pro-flex": 30.0,
        }
        for model_id, cost in expected.items():
            with self.subTest(model_id=model_id):
                self.assertAlmostEqual(
                    _approximate_cost_usd(f"openai/{model_id}", 1_000_000, 1_000_000, 0),
                    cost,
                )
        self.assertIsNone(
            _approximate_cost_usd("gpt-6-astra-fastest", 1_000_000, 1_000_000, 0)
        )

    def test_exact_variant_price_override_wins_before_inherited_base_fallback(self) -> None:
        overrides = {
            "gpt-6-astra": (4.0, 16.0, None),
            "gpt-6-astra-fast": (7.0, 23.0, None),
        }
        self.assertAlmostEqual(
            _approximate_cost_usd(
                "openai/gpt-6-astra-fast", 1_000_000, 1_000_000, 0, overrides
            ),
            30.0,
        )
        self.assertAlmostEqual(
            _approximate_cost_usd(
                "openai/gpt-6-astra-pro-flex", 1_000_000, 1_000_000, 0, overrides
            ),
            10.0,
        )

    def test_the_users_rate_beats_the_shipped_ballpark(self) -> None:
        shipped = _approximate_cost_usd("claude-fable-5-1", 1_000_000, 0, 0)
        overridden = _approximate_cost_usd(
            "claude-fable-5-1", 1_000_000, 0, 0, {"claude-fable-5-1": (1.0, 2.0, None)}
        )
        self.assertAlmostEqual(shipped, 10.0)
        self.assertAlmostEqual(overridden, 1.0)

    def test_a_model_the_shipped_table_never_priced_can_be_priced(self) -> None:
        # The only route to a cost for a model OMH ships no rate for -- a
        # local model, a gateway id, a generation onboarded before its rate
        # was published.
        self.assertIsNone(_approximate_cost_usd("some-unlisted-model", 1_000_000, 0, 0))
        self.assertAlmostEqual(
            _approximate_cost_usd(
                "some-unlisted-model",
                1_000_000,
                1_000_000,
                0,
                {"some-unlisted-model": (0.2, 1.5, None)},
            ),
            1.7,
        )

    def test_an_overridden_model_keeps_the_shipped_cache_ratio_unless_told_otherwise(self) -> None:
        # claude-fable-5-1 ships a 0.025 cache ratio; an override that does not
        # mention the ratio must not silently reset it to the 0.1 default.
        with_shipped_ratio = _approximate_cost_usd(
            "claude-fable-5-1", 0, 0, 1_000_000, {"claude-fable-5-1": (10.0, 50.0, None)}
        )
        self.assertIsNone(with_shipped_ratio)  # no input/output tokens: nothing to price
        priced = _approximate_cost_usd(
            "claude-fable-5-1", 1_000, 0, 1_000_000, {"claude-fable-5-1": (10.0, 50.0, None)}
        )
        self.assertAlmostEqual(priced, (1_000 * 10.0 + 1_000_000 * 10.0 * 0.025) / 1_000_000)

    def test_every_shipped_rate_carries_its_source(self) -> None:
        # A rate without a vendor page and a month is unauditable: a reader
        # cannot tell a current price from one that drifted, which is how the
        # Claude rows went stale before anyone noticed. Each rate must have a
        # citation comment somewhere in the block above it.
        import inspect

        from omh.plugin_bundle.omh import hermes_delegation

        source = inspect.getsource(hermes_delegation)
        block = source.split("APPROX_PRICE_PER_MTOK: dict[str, tuple[float, float]] = {", 1)[1]
        block = block.split("\n}", 1)[0]
        cited = 0
        for line in block.splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                cited = 1 if "pricing" in stripped or "list price" in stripped else cited
            elif stripped.startswith('"'):
                self.assertTrue(cited, f"{stripped} has no price source above it")

    def test_a_zero_rate_is_a_real_price_not_an_absent_one(self) -> None:
        # A free tier bills nothing; the override must be able to say so.
        self.assertEqual(
            _approximate_cost_usd("m", 1_000_000, 1_000_000, 0, {"m": (0.0, 0.0, None)}),
            0.0,
        )


if __name__ == "__main__":
    unittest.main()
