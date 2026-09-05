"""Contracts for the Hermes-native delegation observation feeding the HUD.

The reader joins three Hermes-owned surfaces (`state.db` sessions +
`session_model_usage`, `async_delegations`, and the live transcript manifests)
into HUD activity rows. These tests build a throwaway `$HERMES_HOME` with the
same shapes Hermes v0.20.x writes and pin the projection: identity, model and
effort, mixture-category attribution (including the deliberate ``inherit``
label), liveness windows, and the read_omh_hud merge.
"""

import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from omh.coding.model_contracts import MODEL_CONTRACTS
from omh.plugin_bundle.omh import hermes_delegation as hermes_delegation_module
from omh.plugin_bundle.omh.hermes_delegation import (
    COMPLETED_LINGER_SECONDS,
    DELEGATION_ROUTE_PROVENANCE_SCHEMA_VERSION,
    DECLARED_MODEL_ALIAS_PROJECTIONS,
    HERMES_MIXTURE_CATEGORY_CHAINS,
    MIXTURE_CHAIN_OVERRIDES_SCHEMA_VERSION,
    RECENT_ACTIVITY_SECONDS,
    append_delegation_route_provenance,
    effective_mixture_category_chains,
    load_delegation_route_provenance,
    load_mixture_chain_overrides,
    mixture_category_for,
    mixture_chain_overrides_path,
    parse_model_provider_routes,
    provider_serves_alias,
    read_hermes_native_subagents,
)

NOW = 1_800_000_000.0
PARENT_ID = "20260818_100000_parent"


def _build_state_db(
    home: Path,
    children: list[dict],
    *,
    delegation_states: dict[str, str] | None = None,
    include_cost_provenance: bool = True,
) -> None:
    connection = sqlite3.connect(home / "state.db")
    connection.executescript(
        """
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, model TEXT, model_config TEXT,
            started_at REAL NOT NULL
        );
        CREATE TABLE session_model_usage (
            session_id TEXT NOT NULL, model TEXT NOT NULL,
            api_call_count INTEGER NOT NULL DEFAULT 0,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cache_read_tokens INTEGER NOT NULL DEFAULT 0,
            actual_cost_usd REAL NOT NULL DEFAULT 0,
            estimated_cost_usd REAL NOT NULL DEFAULT 0,
            cost_status TEXT, cost_source TEXT,
            first_seen REAL, last_seen REAL
        );
        CREATE TABLE async_delegations (
            delegation_id TEXT PRIMARY KEY, state TEXT NOT NULL,
            dispatched_at REAL NOT NULL
        );
        """
    )
    if not include_cost_provenance:
        connection.execute("ALTER TABLE session_model_usage DROP COLUMN cost_status")
        connection.execute("ALTER TABLE session_model_usage DROP COLUMN cost_source")
    connection.execute(
        "INSERT INTO sessions VALUES (?, ?, ?, ?)",
        (PARENT_ID, "gpt-5.6-sol", "", NOW - 4000),
    )
    for child in children:
        config = {
            "_delegate_from": PARENT_ID,
            "reasoning_config": {"enabled": True, "effort": child.get("effort", "medium")},
        }
        connection.execute(
            "INSERT INTO sessions VALUES (?, ?, ?, ?)",
            (child["id"], child["model"], json.dumps(config), child["started_at"]),
        )
        usages = child.get("usages")
        if usages is None:
            single = child.get("usage")
            usages = [single] if single else []
        for usage in usages:
            connection.execute(
                (
                    "INSERT INTO session_model_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                    if include_cost_provenance
                    else "INSERT INTO session_model_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                ),
                (
                    child["id"], child["model"], usage.get("api_calls", 0),
                    usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                    usage.get("cache_read_tokens", 0), usage.get("actual_cost_usd", 0.0),
                    usage.get("estimated_cost_usd", 0.0),
                    *(([usage.get("cost_status"), usage.get("cost_source")] if include_cost_provenance else [])),
                    usage.get("first_seen"), usage.get("last_seen"),
                ),
            )
    for delegation_id, state in (delegation_states or {}).items():
        connection.execute(
            "INSERT INTO async_delegations VALUES (?, ?, ?)",
            (delegation_id, state, NOW - 600),
        )
    connection.commit()
    connection.close()


def _write_manifest(
    home: Path, delegation_id: str, goals: list[str], *, started: float, log_mtime: float
) -> None:
    directory = home / "cache" / "delegation" / "live" / delegation_id
    directory.mkdir(parents=True)
    tasks = []
    for index, goal in enumerate(goals):
        log_path = directory / f"task-{index}.log"
        log_path.write_text("header\n", encoding="utf-8")
        import os

        os.utime(log_path, (log_mtime, log_mtime))
        tasks.append({"index": index, "goal": goal, "log": str(log_path), "status": "running"})
    manifest = {
        "delegation_id": delegation_id,
        "started": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started)),
        "task_count": len(tasks),
        "tasks": tasks,
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )


class MixtureCategoryProjectionTest(unittest.TestCase):
    def test_exact_contract_mirror_stays_in_parity_with_core(self) -> None:
        self.assertEqual(
            getattr(hermes_delegation_module, "EXACT_MODEL_CONTRACT_ALIASES", frozenset()),
            frozenset(MODEL_CONTRACTS),
        )

    def test_future_exact_child_stops_inheriting_stale_plugin_metadata(self) -> None:
        from unittest import mock

        exact_aliases = frozenset((*MODEL_CONTRACTS, "gpt-6-astra-pro"))
        with mock.patch.object(
            hermes_delegation_module,
            "EXACT_MODEL_CONTRACT_ALIASES",
            exact_aliases,
            create=True,
        ):
            self.assertIsNone(provider_serves_alias("gpt-6-astra-pro", "openai"))
            self.assertEqual(mixture_category_for("gpt-6-astra-pro", "xhigh"), "")

    def test_future_exact_child_stops_legacy_speed_suffix_category_fallback(self) -> None:
        from unittest import mock

        exact_aliases = frozenset((*MODEL_CONTRACTS, "gpt-6-astra-fast"))
        with mock.patch.object(
            hermes_delegation_module,
            "EXACT_MODEL_CONTRACT_ALIASES",
            exact_aliases,
        ):
            self.assertEqual(mixture_category_for("gpt-6-astra-fast", "xhigh"), "")

    def test_unknown_astra_speed_suffixes_do_not_gain_a_category(self) -> None:
        for alias in (
            "gpt-6-astra-ultrafast",
            "gpt-6-astra-highspeed",
            "gpt-6-astra-pro-ultrafast",
        ):
            with self.subTest(alias=alias):
                self.assertEqual(mixture_category_for(alias, "xhigh"), "")

    def test_a_child_on_the_parent_model_is_labeled_inherit(self):
        self.assertEqual(
            mixture_category_for("gpt-5.6-sol", "medium", parent_model="gpt-5.6-sol"),
            "inherit",
        )

    def test_a_routed_ultrabrain_child_is_labeled_ultrabrain(self):
        self.assertEqual(
            mixture_category_for("gpt-5.6-sol", "xhigh", parent_model="kimi-k3"),
            "ultrabrain",
        )

    def test_an_effort_mismatch_with_the_chain_entry_yields_no_category(self):
        # gpt-5.6-sol appears only as the ultrabrain head, which declares
        # xhigh; a medium run on a different parent matches nothing and must
        # not be dressed up as a routed ultrabrain dispatch.
        self.assertEqual(
            mixture_category_for("gpt-5.6-sol", "medium", parent_model="kimi-k3"), ""
        )

    def test_head_match_beats_membership_match(self):
        # glm-5.3-flash:low heads `quick`; the head attribution wins over its
        # membership anywhere else.
        self.assertEqual(
            mixture_category_for("glm-5.3-flash", "low", parent_model="kimi-k3"),
            "quick",
        )

    def test_earliest_chain_position_beats_category_order(self):
        # glm-5.2-ultrafast:low sits second in `quick` but only third in
        # `unspecified-low` (which precedes quick in canonical order); the
        # shallower fall-through slot is the likelier route, so the quick
        # label survives glm-5.3-flash taking the quick head.
        self.assertEqual(
            mixture_category_for("glm-5.2-ultrafast", "low", parent_model="kimi-k3"),
            "quick",
        )

    def test_a_53_generation_head_labels_its_category(self):
        self.assertEqual(
            mixture_category_for("glm-5.3", "low", parent_model="kimi-k3"),
            "unspecified-low",
        )

    def test_a_highspeed_variant_projects_onto_its_base_models_category(self):
        # Z.ai serves its own 5.3 speed tier as glm-5.3-highspeed; the chains
        # name only the base model, so the variant projects onto it.
        self.assertEqual(
            mixture_category_for("glm-5.3-highspeed", "low", parent_model="kimi-k3"),
            "unspecified-low",
        )

    def test_a_membership_only_model_falls_back_to_its_first_chain(self):
        self.assertEqual(
            mixture_category_for("claude-opus-5", "medium", parent_model="kimi-k3"),
            "unspecified-high",
        )

    def test_an_effort_that_matches_no_chain_entry_is_not_attributed(self):
        # Every category now declares its effort (owner decision), so a child
        # whose effort matches no entry — e.g. an inherited medium on the
        # quick chain's model — shows the bare model, not a routed category.
        self.assertEqual(
            mixture_category_for("glm-5.2-ultrafast", "medium", parent_model="kimi-k3"),
            "",
        )

    def test_an_ultrafast_variant_projects_onto_its_base_models_category(self):
        # Providers serve some chain models through speed variants (e.g. the
        # OpenGateway Ultrafast tier: kimi-k3 via kimi-k3-ultrafast); the
        # variant projects onto the base model's category instead of leaving
        # the HUD row unlabeled.
        self.assertEqual(
            mixture_category_for("kimi-k3-ultrafast", "xhigh", parent_model="gpt-5.6-sol"),
            "architect",
        )
        self.assertEqual(
            mixture_category_for("kimi-k3-ultrafast", "low", parent_model="gpt-5.6-sol"),
            "quick",
        )
        # An explicitly-named variant still matches itself first.
        self.assertEqual(
            mixture_category_for("glm-5.2-ultrafast", "low", parent_model="kimi-k3"),
            "quick",
        )
        # The effort contract still applies to the base-model retry.
        self.assertEqual(
            mixture_category_for("kimi-k3-ultrafast", "max", parent_model="gpt-5.6-sol"),
            "",
        )

    def test_a_routed_architect_child_is_labeled_architect(self):
        self.assertEqual(
            mixture_category_for("claude-fable-5", "xhigh", parent_model="kimi-k3"),
            "architect",
        )

    def test_declared_astra_forms_inherit_category_and_provider_eligibility(self):
        from omh.coding.model_contracts import DECLARED_MODEL_CONTRACT_PROJECTIONS

        expected = {
            model_id: (
                projection["contract_model_id"],
                projection["reasoning_mode"],
                projection["service_tier"],
            )
            for model_id, projection in DECLARED_MODEL_CONTRACT_PROJECTIONS.items()
        }
        self.assertEqual(DECLARED_MODEL_ALIAS_PROJECTIONS, expected)
        for model_id in ("gpt-6-astra", *expected):
            requested = f"openai/{model_id}"
            with self.subTest(model_id=model_id):
                self.assertEqual(
                    mixture_category_for(requested, "xhigh", parent_model="kimi-k3"),
                    "ultrabrain",
                )
                self.assertIs(provider_serves_alias(requested, "openai"), True)
                self.assertIs(provider_serves_alias(requested, "anthropic"), False)

        unknown = "openai/gpt-6-astra-pro-turbo"
        self.assertEqual(mixture_category_for(unknown, "xhigh", parent_model="kimi-k3"), "")
        self.assertIsNone(provider_serves_alias(unknown, "openai"))


def _write_overrides(omh_home: Path, document: object) -> Path:
    path = mixture_chain_overrides_path(omh_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


class ClaudeFableTierContractTest(unittest.TestCase):
    def test_every_hermes_lane_claude_row_declares_an_effort(self):
        # Hermes defaults an unset effort to medium, not the API default high,
        # so a blank Claude row would silently run below its lane's intent.
        for category, chain in HERMES_MIXTURE_CATEGORY_CHAINS.items():
            for alias, effort in chain:
                if alias.startswith("claude-"):
                    self.assertTrue(effort, f"{category}: {alias} has no declared effort")

    def test_fable_51_cache_reads_use_the_documented_lower_ratio(self):
        from omh.plugin_bundle.omh.hermes_delegation import _approximate_cost_usd

        # 1M input at $10 + 1M cache reads at $0.25 + 0 output.
        self.assertAlmostEqual(_approximate_cost_usd("claude-fable-5-1", 1_000_000, 0, 1_000_000), 10.25)
        self.assertAlmostEqual(_approximate_cost_usd("claude-mythos-5-1", 1_000_000, 0, 1_000_000), 10.25)
        # The uniform tenth still applies where no rate is documented.
        self.assertAlmostEqual(_approximate_cost_usd("claude-opus-5", 1_000_000, 0, 1_000_000), 5.5)


class MixtureChainOverridesTest(unittest.TestCase):
    """~/.omh/routing/model-chains.json is the user's chain customization
    surface: it replaces only the categories it names, keeps the category
    vocabulary closed, and an invalid document is ignored whole rather than
    half-applied."""

    def test_an_absent_document_yields_shipped_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            overrides, status = load_mixture_chain_overrides(tmp)
            self.assertEqual((overrides, status), ({}, "absent"))
            self.assertEqual(
                effective_mixture_category_chains(tmp), HERMES_MIXTURE_CATEGORY_CHAINS
            )

    def test_a_seeded_empty_document_applies_and_keeps_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_overrides(Path(tmp), {
                "schema_version": MIXTURE_CHAIN_OVERRIDES_SCHEMA_VERSION,
                "categories": {},
            })
            overrides, status = load_mixture_chain_overrides(tmp)
            self.assertEqual((overrides, status), ({}, "applied"))
            self.assertEqual(
                effective_mixture_category_chains(tmp), HERMES_MIXTURE_CATEGORY_CHAINS
            )

    def test_a_named_category_is_replaced_and_the_rest_stay_shipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            _write_overrides(Path(tmp), {
                "schema_version": MIXTURE_CHAIN_OVERRIDES_SCHEMA_VERSION,
                "categories": {
                    "quick": [
                        {"model": "kimi-k3-ultrafast", "reasoning_effort": "low"},
                        {"model": "glm-5.2-ultrafast", "reasoning_effort": "low"},
                    ]
                },
            })
            chains = effective_mixture_category_chains(tmp)
            self.assertEqual(
                chains["quick"],
                (("kimi-k3-ultrafast", "low"), ("glm-5.2-ultrafast", "low")),
            )
            self.assertEqual(chains["deep"], HERMES_MIXTURE_CATEGORY_CHAINS["deep"])
            # The custom head labels its children like a shipped one.
            self.assertEqual(
                mixture_category_for(
                    "kimi-k3-ultrafast", "low", parent_model="claude-opus-5", chains=chains
                ),
                "quick",
            )

    def test_an_invalid_document_is_ignored_whole(self):
        cases = {
            "wrong schema": {"schema_version": "nope/v9", "categories": {}},
            "unknown category": {
                "schema_version": MIXTURE_CHAIN_OVERRIDES_SCHEMA_VERSION,
                "categories": {"warp-drive": [{"model": "kimi-k3"}]},
            },
            "non-token model": {
                "schema_version": MIXTURE_CHAIN_OVERRIDES_SCHEMA_VERSION,
                "categories": {"quick": [{"model": "bad model\nname"}]},
            },
            "empty chain": {
                "schema_version": MIXTURE_CHAIN_OVERRIDES_SCHEMA_VERSION,
                "categories": {"quick": []},
            },
        }
        for label, document in cases.items():
            with self.subTest(case=label), tempfile.TemporaryDirectory() as tmp:
                _write_overrides(Path(tmp), document)
                overrides, status = load_mixture_chain_overrides(tmp)
                self.assertEqual(overrides, {})
                self.assertTrue(status.startswith("invalid:"), status)
                self.assertEqual(
                    effective_mixture_category_chains(tmp),
                    HERMES_MIXTURE_CATEGORY_CHAINS,
                )

    def test_provider_routes_reject_non_string_scalars(self):
        routes, status = parse_model_provider_routes(
            {
                "schema_version": "model_provider_routes/v1",
                "models": {
                    "quick": {
                        "provider": 123,
                        "model": True,
                    }
                },
            }
        )

        self.assertEqual(routes, {})
        self.assertTrue(status.startswith("invalid:"), status)

    def test_the_embedded_chains_mirror_the_shipped_recommendation_catalog(self):
        from omh.coding.model_recommendations import SHIPPED_MODEL_RECOMMENDATIONS
        from omh.coding.model_routing import MODEL_CATEGORIES

        shipped = {
            category: tuple(
                (str(entry["model_alias"]), str(entry.get("reasoning_effort", "")))
                for entry in chain
            )
            for category, chain in SHIPPED_MODEL_RECOMMENDATIONS["categories"].items()
        }
        self.assertEqual(HERMES_MIXTURE_CATEGORY_CHAINS, shipped)
        # Attribution order is the canonical category order; a reordered dict
        # would silently change which chain claims a shared model.
        self.assertEqual(tuple(HERMES_MIXTURE_CATEGORY_CHAINS), MODEL_CATEGORIES)


class HermesNativeSubagentReaderTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)

    def test_a_missing_hermes_home_reads_as_idle(self):
        payload = read_hermes_native_subagents(self.home / "absent", now=NOW, omh_home=self.home / ".omh")
        self.assertEqual(payload["status"], "idle")
        self.assertEqual(payload["rows"], [])
        self.assertEqual(payload["active"], 0)

    def test_provider_wire_child_uses_configured_alias_and_provider(self):
        route_path = self.home / "routing" / "model-providers.json"
        route_path.parent.mkdir(parents=True)
        route_path.write_text(
            json.dumps(
                {
                    "schema_version": "model_provider_routes/v1",
                    "models": {
                        "glm-5.2-ultrafast": {
                            "provider": "gateway",
                            "model": "z-ai/glm-5.2-ultrafast",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260818_100100_provider",
                    "model": "z-ai/glm-5.2-ultrafast",
                    "effort": "low",
                    "started_at": NOW - 60,
                    "usage": {"last_seen": NOW - 5, "output_tokens": 10},
                }
            ],
        )

        row = read_hermes_native_subagents(
            self.home,
            now=NOW,
            omh_home=self.home,
        )["rows"][0]

        self.assertEqual(row["alias"], "glm-5.2-ultrafast")
        self.assertEqual(row["provider"], "gateway")
        self.assertEqual(row["provider_source"], "model_provider_routes")
        self.assertEqual(row["model"], "z-ai/glm-5.2-ultrafast")
        self.assertEqual(row["category"], "quick")

    def test_a_live_child_projects_a_running_row_with_model_effort_and_metrics(self):
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260818_100100_aaaa11",
                    "model": "gpt-5.6-sol",
                    "effort": "medium",
                    "started_at": NOW - 300,
                    "usage": {
                        "api_calls": 7,
                        "input_tokens": 10_000,
                        "output_tokens": 4_000,
                        "cache_read_tokens": 30_000,
                        "first_seen": NOW - 290,
                        "last_seen": NOW - 10,
                    },
                }
            ],
        )
        _write_manifest(
            self.home,
            "deleg_test1",
            ["구현 lane"],
            started=NOW - 305,
            log_mtime=NOW - 5,
        )
        payload = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home / ".omh")
        self.assertEqual(payload["status"], "observed")
        self.assertEqual(payload["running"], 1)
        row = payload["rows"][0]
        self.assertEqual(row["state"], "running")
        self.assertEqual(row["task_id"], "aaaa11")
        self.assertEqual(row["role"], "hermes-native")
        self.assertEqual(row["action"], "구현 lane")
        self.assertEqual(row["model"], "gpt-5.6-sol")
        self.assertEqual(row["effort"], "medium")
        self.assertEqual(row["category"], "inherit")
        self.assertEqual(row["tokens"], 14_000)
        self.assertEqual(row["turn_count"], 7)
        self.assertEqual(row["delegation_id"], "deleg_test1")
        self.assertAlmostEqual(row["cache_hit_percentage"], 75.0)
        self.assertAlmostEqual(row["tokens_per_second"], 4000 / 280)
        # The host recorded no cost (subscription billing), so the row carries
        # the token-derived approximation, flagged so the widget renders `~$`:
        # 10k input @ $1.25/M + 30k cache reads @ a tenth of input + 4k output
        # @ $10/M.
        self.assertTrue(row["cost_approximate"])
        self.assertAlmostEqual(
            row["cost_usd"],
            (10_000 * 1.25 + 30_000 * 0.125 + 4_000 * 10.0) / 1_000_000,
        )

    def test_inherited_base_price_override_keeps_operator_provenance(self):
        price_path = self.home / "routing" / "model-prices.json"
        price_path.parent.mkdir(parents=True)
        price_path.write_text(
            json.dumps(
                {
                    "schema_version": "model_price_overrides/v1",
                    "models": {
                        "gpt-6-astra": {
                            "input_per_mtok": 2.0,
                            "output_per_mtok": 3.0,
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260818_100100_pricebase",
                    "model": "gpt-6-astra-fast",
                    "started_at": NOW - 60,
                    "usage": {
                        "input_tokens": 1_000_000,
                        "output_tokens": 1_000_000,
                        "last_seen": NOW - 5,
                    },
                }
            ],
        )
        _write_manifest(
            self.home,
            "deleg_pricebase",
            ["price provenance lane"],
            started=NOW - 65,
            log_mtime=NOW - 5,
        )

        row = read_hermes_native_subagents(
            self.home,
            now=NOW,
            omh_home=self.home,
        )["rows"][0]

        self.assertTrue(row["cost_approximate"])
        self.assertTrue(row["cost_override"])
        self.assertAlmostEqual(row["cost_usd"], 10.0)

    def test_solar_pro2_unrecorded_cost_is_approximated_at_list_price(self):
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260818_100100_solar01",
                    "model": "solar-pro2",
                    "effort": "low",
                    "started_at": NOW - 300,
                    "usage": {
                        "api_calls": 5,
                        "input_tokens": 20_000,
                        "output_tokens": 5_000,
                        "cache_read_tokens": 10_000,
                        "first_seen": NOW - 290,
                        "last_seen": NOW - 10,
                    },
                }
            ],
        )
        _write_manifest(
            self.home,
            "deleg_solar",
            ["solar lane"],
            started=NOW - 305,
            log_mtime=NOW - 5,
        )
        payload = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home / ".omh")
        self.assertEqual(payload["status"], "observed")
        self.assertEqual(payload["running"], 1)
        row = payload["rows"][0]
        self.assertEqual(row["model"], "solar-pro2")
        # Solar Pro 2 list price: $0.15/M input, $0.60/M output; cache reads @ tenth of input ($0.015/M).
        # 20k input @ $0.15/M + 10k cache reads @ $0.015/M + 5k output @ $0.60/M.
        self.assertTrue(row["cost_approximate"])
        self.assertAlmostEqual(
            row["cost_usd"],
            (20_000 * 0.15 + 10_000 * 0.015 + 5_000 * 0.60) / 1_000_000,
        )

    def test_an_unpriceable_unrecorded_cost_is_unknown_rather_than_free(self):
        # Any model the shipped table does not price -- a local model, a
        # gateway id, a generation onboarded before its rate was published --
        # leaves nothing to derive a figure from. The host recorded no cost
        # either (the columns are NOT NULL DEFAULT 0, so "billed nothing" and
        # "recorded nothing" arrive identically as 0.0). The row must then
        # carry NO cost at all: a bare 0.0 with no approximate flag renders
        # exactly like a genuinely free run, which is the claim OMH cannot
        # support. The rule is the point, not the example model -- when the
        # table gains a rate for one, the next unpriced model inherits it.
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260818_100200_unpriced1",
                    "model": "some-unlisted-model",
                    "effort": "medium",
                    "started_at": NOW - 300,
                    "usage": {
                        "api_calls": 3,
                        "input_tokens": 12_000,
                        "output_tokens": 3_000,
                        "cache_read_tokens": 0,
                        "first_seen": NOW - 290,
                        "last_seen": NOW - 10,
                    },
                }
            ],
        )
        _write_manifest(
            self.home,
            "deleg_grok",
            ["grok lane"],
            started=NOW - 305,
            log_mtime=NOW - 5,
        )
        payload = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home / ".omh")
        row = payload["rows"][0]
        self.assertEqual(row["model"], "some-unlisted-model")
        self.assertEqual(row["tokens"], 15_000)
        self.assertNotIn("cost_usd", row)
        self.assertNotIn("cost_approximate", row)

    def test_mixed_billed_and_included_rows_keep_the_positive_aggregate(self):
        # Given: one child whose usage rows mix a billed $12.50 row with an
        # included zero row, so MAX(cost_status) surfaces "included" while
        # SUM(actual_cost_usd) is still positive
        _build_state_db(
            self.home,
            [{
                "id": "20260818_100100_mixed001",
                "model": "gpt-5.6-sol",
                "started_at": NOW - 60,
                "usages": [
                    {
                        "input_tokens": 100_000,
                        "output_tokens": 20_000,
                        "actual_cost_usd": 12.50,
                        "cost_status": "billed",
                        "cost_source": "gateway",
                        "first_seen": NOW - 55,
                        "last_seen": NOW - 30,
                    },
                    {
                        "input_tokens": 10_000,
                        "output_tokens": 4_000,
                        "actual_cost_usd": 0.0,
                        "cost_status": "included",
                        "cost_source": "subscription",
                        "first_seen": NOW - 25,
                        "last_seen": NOW - 5,
                    },
                ],
            }],
        )
        _write_manifest(self.home, "deleg_mixed", ["mixed lane"], started=NOW - 65, log_mtime=NOW - 5)
        # When: the reader projects the child
        row = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home)["rows"][0]
        # Then: the positive observed aggregate stands -- a provenance word
        # may annotate a zero, it may never erase an observed figure
        self.assertEqual(row["cost_usd"], 12.50)
        self.assertNotIn("cost_approximate", row)

    def test_a_billed_zero_status_keeps_the_zero_exact(self):
        # Given: a host that confirms it billed nothing, in a status word OMH
        # does not know (provenance is host-vocabulary-neutral)
        _build_state_db(
            self.home,
            [{
                "id": "20260818_100100_billedzero",
                "model": "gpt-5.6-sol",
                "started_at": NOW - 60,
                "usage": {
                    "input_tokens": 10_000,
                    "output_tokens": 4_000,
                    "actual_cost_usd": 0.0,
                    "cost_status": "billed_zero",
                    "cost_source": "gateway",
                    "last_seen": NOW - 5,
                },
            }],
        )
        _write_manifest(self.home, "deleg_bz", ["billed-zero lane"], started=NOW - 65, log_mtime=NOW - 5)
        # When: the reader projects the child
        row = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home)["rows"][0]
        # Then: the confirmed zero stays exact -- any recorded provenance
        # vouches for it, so no approximation may overwrite it
        self.assertEqual(row["cost_usd"], 0.0)
        self.assertEqual(row["cost_status"], "billed_zero")
        self.assertEqual(row["cost_source"], "gateway")
        self.assertNotIn("cost_approximate", row)

    def test_source_only_provenance_keeps_the_zero_exact(self):
        # Given: a zero whose only provenance is a recorded source (the
        # status column stayed NULL on every usage row)
        _build_state_db(
            self.home,
            [{
                "id": "20260818_100100_srconly1",
                "model": "gpt-5.6-sol",
                "started_at": NOW - 60,
                "usage": {
                    "input_tokens": 10_000,
                    "output_tokens": 4_000,
                    "actual_cost_usd": 0.0,
                    "cost_status": None,
                    "cost_source": "subscription",
                    "last_seen": NOW - 5,
                },
            }],
        )
        _write_manifest(self.home, "deleg_src", ["source lane"], started=NOW - 65, log_mtime=NOW - 5)
        # When: the reader projects the child
        row = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home)["rows"][0]
        # Then: source-only provenance still vouches for the zero
        self.assertEqual(row["cost_usd"], 0.0)
        self.assertNotIn("cost_status", row)
        self.assertEqual(row["cost_source"], "subscription")
        self.assertNotIn("cost_approximate", row)

    def test_a_confirmed_billed_zero_keeps_exact_zero_and_provenance(self):
        _build_state_db(
            self.home,
            [{
                "id": "20260818_100100_zero0001",
                "model": "gpt-5.6-sol",
                "started_at": NOW - 60,
                "usage": {
                    "input_tokens": 10_000,
                    "output_tokens": 4_000,
                    "actual_cost_usd": 0.0,
                    "cost_status": "included",
                    "cost_source": "subscription",
                    "last_seen": NOW - 5,
                },
            }],
        )
        _write_manifest(self.home, "deleg_zero", ["zero lane"], started=NOW - 65, log_mtime=NOW - 5)
        row = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home)["rows"][0]
        self.assertEqual(row["cost_usd"], 0.0)
        self.assertEqual(row["cost_status"], "included")
        self.assertEqual(row["cost_source"], "subscription")
        self.assertNotIn("cost_approximate", row)

    def test_absent_cost_provenance_still_approximates_zero(self):
        _build_state_db(
            self.home,
            [{
                "id": "20260818_100100_absent01",
                "model": "gpt-5.6-sol",
                "started_at": NOW - 60,
                "usage": {
                    "input_tokens": 10_000,
                    "output_tokens": 4_000,
                    "actual_cost_usd": 0.0,
                    "estimated_cost_usd": 0.0,
                    "last_seen": NOW - 5,
                },
            }],
        )
        _write_manifest(self.home, "deleg_absent", ["absent lane"], started=NOW - 65, log_mtime=NOW - 5)
        row = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home)["rows"][0]
        self.assertGreater(row["cost_usd"], 0.0)
        self.assertTrue(row["cost_approximate"])
        self.assertNotIn("cost_status", row)
        self.assertNotIn("cost_source", row)

    def test_legacy_schema_preserves_usage_and_approximates_zero(self):
        _build_state_db(
            self.home,
            [{
                "id": "20260818_100100_legacy01",
                "model": "gpt-5.6-sol",
                "started_at": NOW - 60,
                "usage": {
                    "input_tokens": 10_000,
                    "output_tokens": 4_000,
                    "actual_cost_usd": 0.0,
                    "last_seen": NOW - 5,
                },
            }],
            include_cost_provenance=False,
        )
        _write_manifest(self.home, "deleg_legacy", ["legacy lane"], started=NOW - 65, log_mtime=NOW - 5)
        row = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home)["rows"][0]
        self.assertEqual(row["tokens"], 14_000)
        self.assertGreater(row["cost_usd"], 0.0)
        self.assertTrue(row["cost_approximate"])
        self.assertNotIn("cost_status", row)
        self.assertNotIn("cost_source", row)

    def test_an_observed_host_cost_is_never_replaced_by_the_approximation(self):
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260818_100100_bbbb77",
                    "model": "gpt-5.6-sol",
                    "started_at": NOW - 60,
                    "usage": {
                        "input_tokens": 10_000,
                        "output_tokens": 4_000,
                        "actual_cost_usd": 0.5,
                        "last_seen": NOW - 5,
                    },
                }
            ],
        )
        _write_manifest(
            self.home, "deleg_paid", ["paid lane"], started=NOW - 65, log_mtime=NOW - 5
        )
        row = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home / ".omh")["rows"][0]
        self.assertEqual(row["cost_usd"], 0.5)
        self.assertNotIn("cost_approximate", row)

    def test_a_quiet_child_reads_done_and_expires_after_the_linger_window(self):
        quiet_age = RECENT_ACTIVITY_SECONDS + 60
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260818_100100_bbbb22",
                    "model": "gpt-5.6-sol",
                    "started_at": NOW - quiet_age,
                    "usage": {"last_seen": NOW - quiet_age, "output_tokens": 5},
                }
            ],
        )
        payload = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home / ".omh")
        self.assertEqual(payload["rows"][0]["state"], "done")
        self.assertEqual(payload["completed"], 1)
        self.assertEqual(payload["active"], 0)

        expired = read_hermes_native_subagents(
            self.home, now=NOW + COMPLETED_LINGER_SECONDS + 1, omh_home=self.home / ".omh"
        )
        self.assertEqual(expired["rows"], [])
        self.assertEqual(expired["status"], "idle")

    def test_a_finished_row_is_byte_stable_across_polls(self):
        # The widget skips repaints when a snapshot serializes identically,
        # which is what keeps the dock drag-copyable while a done row lingers
        # — so a finished child's row must not vary with the reader's clock.
        quiet_age = RECENT_ACTIVITY_SECONDS + 60
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260818_100100_ffff66",
                    "model": "gpt-5.6-sol",
                    "started_at": NOW - quiet_age,
                    "usage": {"last_seen": NOW - quiet_age, "output_tokens": 5},
                }
            ],
        )
        first = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home / ".omh")
        second = read_hermes_native_subagents(self.home, now=NOW + 30, omh_home=self.home / ".omh")
        self.assertEqual(first["rows"][0]["state"], "done")
        self.assertEqual(first["rows"], second["rows"])

    def test_a_completed_delegation_marks_its_child_done_even_while_recent(self):
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260818_100100_cccc33",
                    "model": "gpt-5.6-sol",
                    "started_at": NOW - 60,
                    "usage": {"last_seen": NOW - 5, "output_tokens": 10},
                }
            ],
            delegation_states={"deleg_done1": "completed"},
        )
        _write_manifest(
            self.home, "deleg_done1", ["끝난 lane"], started=NOW - 65, log_mtime=NOW - 5
        )
        payload = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home / ".omh")
        self.assertEqual(payload["rows"][0]["state"], "done")
        self.assertEqual(payload["completed"], 1)

    def test_a_completed_delegation_with_no_usage_projects_failed(self):
        # Observed live: the billing account rejected the routed model with
        # HTTP 400 ("not supported when using Codex with a ChatGPT account"),
        # the child died in half a second with zero successful API calls, yet
        # Hermes recorded the delegation "completed" and the HUD drew ✓.
        # No recorded model usage on a terminal child means no work happened.
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260818_100100_eeee55",
                    "model": "glm-5.2-ultrafast",
                    "started_at": NOW - 60,
                }
            ],
            delegation_states={"deleg_nousage": "completed"},
        )
        _write_manifest(
            self.home, "deleg_nousage", ["rejected lane"], started=NOW - 65, log_mtime=NOW - 59
        )
        payload = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home / ".omh")
        row = payload["rows"][0]
        self.assertEqual(row["state"], "failed")
        self.assertEqual(row["failure_hint"], "no model usage observed")
        self.assertEqual(payload["blocked"], 1)
        self.assertEqual(payload["completed"], 0)

    def test_a_failed_delegation_projects_a_failed_row_counted_as_blocked(self):
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260818_100100_dddd44",
                    "model": "gpt-5.6-sol",
                    "started_at": NOW - 60,
                    "usage": {"last_seen": NOW - 5, "output_tokens": 10},
                }
            ],
            delegation_states={"deleg_fail1": "failed"},
        )
        _write_manifest(
            self.home, "deleg_fail1", ["실패 lane"], started=NOW - 65, log_mtime=NOW - 5
        )
        payload = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home / ".omh")
        self.assertEqual(payload["rows"][0]["state"], "failed")
        self.assertEqual(payload["blocked"], 1)
        self.assertEqual(payload["active"], 1)


class HudMergeTest(unittest.TestCase):
    def test_read_omh_hud_uses_requested_provider_route_home(self):
        from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / "omh"
            hermes_home = root / "hermes"
            route_path = omh_home / "routing" / "model-providers.json"
            route_path.parent.mkdir(parents=True)
            hermes_home.mkdir()
            route_path.write_text(
                json.dumps(
                    {
                        "schema_version": "model_provider_routes/v1",
                        "models": {
                            "glm-5.2-ultrafast": {
                                "provider": "gateway",
                                "model": "z-ai/glm-5.2-ultrafast",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            _build_state_db(
                hermes_home,
                [
                    {
                        "id": "20260818_100100_provider",
                        "model": "z-ai/glm-5.2-ultrafast",
                        "effort": "low",
                        "started_at": time.time() - 30,
                        "usage": {
                            "api_calls": 1,
                            "output_tokens": 10,
                            "last_seen": time.time() - 1,
                        },
                    }
                ],
            )

            row = read_omh_hud(omh_home, hermes_home)["subagents"]["rows"][0]

            self.assertEqual(row["alias"], "glm-5.2-ultrafast")
            self.assertEqual(row["provider"], "gateway")
            self.assertEqual(row["category"], "quick")

    def test_read_omh_hud_merges_native_rows_and_stays_active_while_they_linger(self):
        from omh.plugin_bundle.omh.runtime_reader import read_omh_hud

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / "omh"
            hermes_home = root / "hermes"
            omh_home.mkdir()
            hermes_home.mkdir()
            _build_state_db(
                hermes_home,
                [
                    {
                        "id": "20260818_100100_eeee55",
                        "model": "gpt-5.6-terra",
                        "effort": "high",
                        "started_at": time.time() - 30,
                        "usage": {
                            "api_calls": 2,
                            "input_tokens": 100,
                            "output_tokens": 50,
                            "first_seen": time.time() - 25,
                            "last_seen": time.time() - 1,
                        },
                    }
                ],
            )
            payload = read_omh_hud(omh_home, hermes_home)
            self.assertTrue(payload["active"])
            self.assertEqual(payload["subagents"]["running"], 1)
            rows = payload["subagents"]["rows"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["role"], "hermes-native")
            # gpt-5.6-terra:high is the deep chain head and differs from the
            # parent model, so the routed category is visible in the HUD row.
            self.assertEqual(rows[0]["category"], "deep")
            # Nothing was dropped, so the disclosed hidden-row count is zero.
            self.assertEqual(payload["subagents"]["hidden_rows"], 0)

    def test_read_omh_hud_caps_many_native_rows_and_discloses_the_drop(self):
        from omh.plugin_bundle.omh.runtime_reader import ACTIVITY_ROW_LIMIT, read_omh_hud

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            omh_home = root / "omh"
            hermes_home = root / "hermes"
            omh_home.mkdir()
            hermes_home.mkdir()
            base = time.time()
            _build_state_db(
                hermes_home,
                [
                    {
                        "id": f"20260818_1001{index:02d}_child{index:02d}",
                        "model": "gpt-5.6-terra",
                        "effort": "high",
                        "started_at": base - 300 + index,
                        "usage": {
                            "api_calls": 1,
                            "output_tokens": 10,
                            "last_seen": base - 1,
                        },
                    }
                    # One more child than the merge cap admits.
                    for index in range(ACTIVITY_ROW_LIMIT + 1)
                ],
            )
            payload = read_omh_hud(omh_home, hermes_home)
            rows = payload["subagents"]["rows"]
            self.assertEqual(len(rows), ACTIVITY_ROW_LIMIT)
            # Every carried row is running (running rows outrank settled ones
            # in the merged ordering) and the one capped row is disclosed so
            # the widget can render `+N more` instead of silently truncating.
            self.assertTrue(all(row["state"] == "running" for row in rows))
            self.assertEqual(payload["subagents"]["hidden_rows"], 1)


if __name__ == "__main__":
    unittest.main()


def _write_provenance(omh_home: Path, records: list[dict]) -> None:
    path = omh_home / "routing" / "route-provenance.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": DELEGATION_ROUTE_PROVENANCE_SCHEMA_VERSION,
                "records": records,
            }
        ),
        encoding="utf-8",
    )


def _record(**overrides) -> dict:
    record = {
        "origin": "fallback",
        "category": "visual-engineering",
        "alias": "glm-5.2-ultrafast",
        "wire_model": "z-ai/glm-5.2-ultrafast",
        "provider": "gateway",
        "reasoning_effort": "low",
        "from_alias": "claude-fable-5",
        "written_at": NOW - 120,
    }
    record.update(overrides)
    return record


class RouteProvenanceStoreTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)

    def test_append_roundtrips_and_caps_history(self):
        for index in range(40):
            status = append_delegation_route_provenance(
                _record(alias=f"m{index}", written_at=1000.0 + index), self.home
            )
            self.assertEqual(status, "recorded")
        records = load_delegation_route_provenance(self.home)
        self.assertEqual(len(records), 32)
        self.assertEqual(records[-1]["alias"], "m39")
        self.assertEqual(records[0]["alias"], "m8")

    def test_an_invalid_record_is_refused_not_written(self):
        self.assertEqual(
            append_delegation_route_provenance(_record(origin="nope"), self.home),
            "unrecorded: invalid record",
        )
        self.assertEqual(load_delegation_route_provenance(self.home), [])

    def test_an_invalid_document_reads_empty_whole(self):
        path = self.home / "routing" / "route-provenance.json"
        path.parent.mkdir(parents=True)
        for document in (
            "not json",
            json.dumps({"schema_version": "wrong/v9", "records": []}),
            json.dumps(
                {
                    "schema_version": DELEGATION_ROUTE_PROVENANCE_SCHEMA_VERSION,
                    "records": [{"origin": "nope", "written_at": 1.0}],
                }
            ),
        ):
            with self.subTest(document=document[:30]):
                path.write_text(document, encoding="utf-8")
                self.assertEqual(load_delegation_route_provenance(self.home), [])


class RouteProvenanceProjectionTest(unittest.TestCase):
    """Prepared-route provenance upgrades HUD labels for matching children."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        route_path = self.home / "routing" / "model-providers.json"
        route_path.parent.mkdir(parents=True)
        route_path.write_text(
            json.dumps(
                {
                    "schema_version": "model_provider_routes/v1",
                    "models": {
                        "glm-5.2-ultrafast": {
                            "provider": "gateway",
                            "model": "z-ai/glm-5.2-ultrafast",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )

    def _row(self, child_model: str) -> dict:
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260818_100200_lane",
                    "model": child_model,
                    "effort": "low",
                    "started_at": NOW - 60,
                    "usage": {"last_seen": NOW - 5, "output_tokens": 10},
                }
            ],
        )
        return read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home)["rows"][0]

    def test_a_fallback_route_labels_its_child_with_category_and_origin(self):
        _write_provenance(self.home, [_record()])
        row = self._row("z-ai/glm-5.2-ultrafast")
        self.assertEqual(row["category"], "visual-engineering")
        self.assertEqual(row["route_origin"], "fallback")
        self.assertEqual(row["category_source"], "route_provenance")

    def test_an_exhausted_chain_child_reads_route_category_to_inherit(self):
        # The child runs the parent model, so the plain projection says
        # inherit; the provenance says WHY — the category chain exhausted.
        _write_provenance(
            self.home,
            [_record(origin="exhausted_to_inherit", alias="", wire_model="", provider="")],
        )
        row = self._row("gpt-5.6-sol")
        self.assertEqual(row["category"], "inherit")
        self.assertEqual(row["route_origin"], "exhausted_to_inherit")
        self.assertEqual(row["route_category"], "visual-engineering")

    def _rows(self, children: list[dict]) -> dict:
        _build_state_db(self.home, children)
        payload = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home)
        return {row["task_id"]: row for row in payload["rows"]}

    def test_an_exhaustion_record_labels_only_the_earliest_inherit_child(self):
        # The record describes exactly one dispatch — the next inherit child
        # after the chain cleared. A later inherit lane is an ordinary
        # unrouted delegation and must NOT be claimed.
        _write_provenance(
            self.home,
            [_record(origin="exhausted_to_inherit", alias="", wire_model="", provider="")],
        )
        rows = self._rows(
            [
                {
                    "id": "20260818_100300_first",
                    "model": "gpt-5.6-sol",
                    "effort": "medium",
                    "started_at": NOW - 90,
                    "usage": {"last_seen": NOW - 5, "output_tokens": 10},
                },
                {
                    "id": "20260818_100400_second",
                    "model": "gpt-5.6-sol",
                    "effort": "medium",
                    "started_at": NOW - 40,
                    "usage": {"last_seen": NOW - 5, "output_tokens": 10},
                },
            ]
        )
        self.assertEqual(rows["first"]["route_origin"], "exhausted_to_inherit")
        self.assertNotIn("route_origin", rows["second"])
        self.assertEqual(rows["second"]["category"], "inherit")

    def test_an_exhaustion_record_beyond_its_tight_window_claims_nothing(self):
        # 800s after the chain cleared, an inherit lane is an ordinary
        # unrouted delegation, not the exhausted chain's re-dispatch.
        _write_provenance(
            self.home,
            [
                _record(
                    origin="exhausted_to_inherit",
                    alias="",
                    wire_model="",
                    provider="",
                    written_at=NOW - 860,
                )
            ],
        )
        row = self._row("gpt-5.6-sol")
        self.assertEqual(row["category"], "inherit")
        self.assertNotIn("route_origin", row)

    def test_a_cleared_route_supersedes_the_record_before_it(self):
        _write_provenance(
            self.home,
            [
                _record(written_at=NOW - 300),
                {"origin": "cleared", "written_at": NOW - 200},
            ],
        )
        row = self._row("z-ai/glm-5.2-ultrafast")
        self.assertNotIn("route_origin", row)
        self.assertNotIn("category_source", row)
        self.assertEqual(row["category"], "quick")

    def test_inherit_wins_over_a_matching_routed_record(self):
        # The parent's own model can also be a chain member; a child that
        # inherited it was NOT routed, whatever the prepared route said.
        _write_provenance(
            self.home,
            [_record(alias="gpt-5.6-sol", wire_model="gpt-5.6-sol", provider="")],
        )
        row = self._row("gpt-5.6-sol")
        self.assertEqual(row["category"], "inherit")
        self.assertNotIn("route_origin", row)
        self.assertNotIn("category_source", row)

    def test_a_newer_unrelated_record_blocks_an_older_matching_one(self):
        # Only the newest record written before the dispatch describes it;
        # an older matching record was already replaced for this lane.
        _write_provenance(
            self.home,
            [
                _record(written_at=NOW - 300),
                _record(
                    origin="head",
                    category="ultrabrain",
                    alias="gpt-5.6-sol",
                    wire_model="gpt-5.6-sol",
                    provider="",
                    written_at=NOW - 100,
                ),
            ],
        )
        row = self._row("z-ai/glm-5.2-ultrafast")
        self.assertNotIn("route_origin", row)
        self.assertEqual(row["category"], "quick")

    def test_the_written_document_carries_a_claim_boundary(self):
        append_delegation_route_provenance(_record(), self.home)
        document = json.loads(
            (self.home / "routing" / "route-provenance.json").read_text(encoding="utf-8")
        )
        self.assertIn("Prepared routes only", document["claim_boundary"])

    def test_stale_or_mismatched_provenance_never_upgrades_a_label(self):
        for records in (
            [_record(written_at=NOW - 2000)],           # older than freshness
            [_record(written_at=NOW - 10)],             # written after dispatch
            [_record(wire_model="other/model", alias="other")],  # different route
        ):
            with self.subTest(records=records):
                _write_provenance(self.home, records)
                (self.home / "state.db").unlink(missing_ok=True)
                row = self._row("z-ai/glm-5.2-ultrafast")
                self.assertNotIn("route_origin", row)
                self.assertEqual(row["category"], "quick")
