"""Contracts for the Hermes-native delegation observation feeding the HUD.

The reader joins three Hermes-owned surfaces (`state.db` sessions +
`session_model_usage`, `async_delegations`, and the live transcript manifests)
into HUD activity rows. These tests build a throwaway `$HERMES_HOME` with the
same shapes Hermes v0.20.x writes and pin the projection: identity, model and
effort, mixture-category attribution (including the deliberate ``inherit``
label), liveness windows, and the read_omh_hud merge.
"""

import hashlib
import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from omh.coding.model_contracts import MODEL_CONTRACTS
from omh.plugin_bundle.omh import hermes_delegation as hermes_delegation_module
from omh.plugin_bundle.omh.hermes_delegation import (
    ATTESTATION_COVERAGE_CLAIM,
    _ACTION_LIMIT,
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
    is_provider_id_token,
    parse_mixture_chain_overrides,
    parse_model_price_overrides,
    parse_provider_entitlements,
    mixture_category_for,
    mixture_chain_overrides_path,
    parse_model_provider_routes,
    provider_serves_alias,
    read_hermes_native_subagents,
    served_model_attestation,
    _prompt_identity_model,
)

NOW = 1_800_000_000.0
PARENT_ID = "20260818_100000_parent"


def _identity_prompt(model: str, *, earlier: str = "", runtime: str | None = None) -> str:
    """A stored system prompt in the shape Hermes builds one.

    The last paragraph is the identity trailer (`_timestamp_line`), optionally
    followed by the renderer's runtime block; `earlier` stands for memory or
    context-file prose ahead of it.
    """
    prompt = "You are a helpful agent.\n\n"
    if earlier:
        prompt += earlier + "\n\n"
    prompt += "Conversation started: Monday, August 18, 2026"
    if model:
        prompt += f"\nModel: {model}"
    prompt += "\nProvider: openrouter\nPlatform: cli"
    if runtime is not None:
        prompt += (
            "\n\n# Hermes runtime environment\n\n"
            f"{runtime}\n\n<!-- End Hermes runtime environment -->"
        )
    return prompt


def _build_state_db(
    home: Path,
    children: list[dict],
    *,
    delegation_states: dict[str, str] | None = None,
    include_cost_provenance: bool = True,
    include_end_columns: bool = False,
    include_prompt_columns: bool = False,
    include_usage_task: bool = False,
) -> None:
    connection = sqlite3.connect(home / "state.db")
    # `parent_session_id` and the stored system prompt are what attest a
    # child's request; without them the table is a schema that cannot. Off by
    # default: other suites extend this four-column shape themselves.
    prompt_columns = (
        ", parent_session_id TEXT, system_prompt TEXT, system_prompt_hash TEXT"
        if include_prompt_columns
        else ""
    )
    # Hermes soft-archives compacted rows (`active = 0`); a row that has any
    # may have had its stored prompt rebuilt.
    message_columns = ", active INTEGER NOT NULL DEFAULT 1" if include_prompt_columns else ""
    connection.executescript(
        f"""
        CREATE TABLE sessions (
            id TEXT PRIMARY KEY, model TEXT, model_config TEXT,
            started_at REAL NOT NULL{prompt_columns}
        );
        CREATE TABLE system_prompts (hash TEXT PRIMARY KEY, prompt TEXT NOT NULL);
        CREATE TABLE session_model_usage (
            session_id TEXT NOT NULL, model TEXT NOT NULL,
            billing_provider TEXT NOT NULL DEFAULT '',
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
        CREATE TABLE messages (
            session_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT{message_columns}
        );
        """
    )
    if not include_cost_provenance:
        connection.execute("ALTER TABLE session_model_usage DROP COLUMN cost_status")
        connection.execute("ALTER TABLE session_model_usage DROP COLUMN cost_source")
    # Without them the table is a state.db from before Hermes stamped a
    # session's end, which the reader must still read.
    if include_end_columns:
        connection.execute("ALTER TABLE sessions ADD COLUMN ended_at REAL")
        connection.execute("ALTER TABLE sessions ADD COLUMN end_reason TEXT")
    # Hermes names an auxiliary call's kind in `task` (`compression`,
    # `vision`, ...) and leaves it empty for the agent's own turns.
    if include_usage_task:
        connection.execute("ALTER TABLE session_model_usage ADD COLUMN task TEXT NOT NULL DEFAULT ''")
    connection.execute(
        "INSERT INTO sessions (id, model, model_config, started_at) VALUES (?, ?, ?, ?)",
        (PARENT_ID, "gpt-5.6-sol", "", NOW - 4000),
    )
    for child in children:
        config = {
            "_delegate_from": PARENT_ID,
            "reasoning_config": {"enabled": True, "effort": child.get("effort", "medium")},
        }
        connection.execute(
            "INSERT INTO sessions (id, model, model_config, started_at) VALUES (?, ?, ?, ?)",
            (child["id"], child["model"], json.dumps(config), child["started_at"]),
        )
        if include_prompt_columns:
            # A child's first segment names the delegating session as its
            # parent; a compression continuation names the previous segment.
            connection.execute(
                "UPDATE sessions SET parent_session_id = ? WHERE id = ?",
                (child.get("parent_session_id", PARENT_ID), child["id"]),
            )
            prompt = child.get("prompt")
            if prompt is None and "prompt_model" in child:
                prompt = _identity_prompt(child["prompt_model"])
            if prompt is not None and child.get("prompt_inline"):
                connection.execute(
                    "UPDATE sessions SET system_prompt = ? WHERE id = ?", (prompt, child["id"])
                )
            elif prompt is not None:
                digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
                connection.execute(
                    "INSERT OR IGNORE INTO system_prompts (hash, prompt) VALUES (?, ?)",
                    (digest, prompt),
                )
                connection.execute(
                    "UPDATE sessions SET system_prompt_hash = ? WHERE id = ?", (digest, child["id"])
                )
        if include_end_columns:
            connection.execute(
                "UPDATE sessions SET ended_at = ?, end_reason = ? WHERE id = ?",
                (child.get("ended_at"), child.get("end_reason"), child["id"]),
            )
        # The dispatch prompt lands as the child's first user row; a child
        # declaring none exercises the reader's empty-label degradation.
        for role, content in child.get("messages", []):
            connection.execute(
                "INSERT INTO messages (session_id, role, content) VALUES (?, ?, ?)",
                (child["id"], role, content),
            )
        for role, content in child.get("archived_messages", []):
            connection.execute(
                "INSERT INTO messages (session_id, role, content, active) VALUES (?, ?, ?, 0)",
                (child["id"], role, content),
            )
        usages = child.get("usages")
        if usages is None:
            single = child.get("usage")
            usages = [single] if single else []
        for usage in usages:
            # Named columns, not positions: the host's real table carries
            # more of them than this fixture does, and a positional insert
            # made adding one a rewrite of every call site.
            values = {
                "session_id": child["id"],
                # The usage table records the model each call ran on, which
                # is not always what the session row holds.
                "model": usage.get("model", child["model"]),
                "billing_provider": usage.get("billing_provider", ""),
                "api_call_count": usage.get("api_calls", 0),
                "input_tokens": usage.get("input_tokens", 0),
                "output_tokens": usage.get("output_tokens", 0),
                "cache_read_tokens": usage.get("cache_read_tokens", 0),
                "actual_cost_usd": usage.get("actual_cost_usd", 0.0),
                "estimated_cost_usd": usage.get("estimated_cost_usd", 0.0),
                "first_seen": usage.get("first_seen"),
                "last_seen": usage.get("last_seen"),
            }
            if include_cost_provenance:
                values["cost_status"] = usage.get("cost_status")
                values["cost_source"] = usage.get("cost_source")
            if include_usage_task:
                values["task"] = usage.get("task", "")
            connection.execute(
                "INSERT INTO session_model_usage ({}) VALUES ({})".format(
                    ", ".join(values), ", ".join("?" for _ in values)
                ),
                tuple(values.values()),
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
            mixture_category_for("gpt-6-astra", "xhigh", parent_model="kimi-k3"),
            "ultrabrain",
        )

    def test_an_effort_mismatch_with_the_chain_entry_yields_no_category(self):
        # gpt-6-astra appears only at xhigh (the ultrabrain head and the
        # architect GPT slot); a medium run on a different parent matches
        # nothing and must not be dressed up as a routed ultrabrain dispatch.
        self.assertEqual(
            mixture_category_for("gpt-6-astra", "medium", parent_model="kimi-k3"), ""
        )

    def test_head_match_beats_membership_match(self):
        # glm-5.3-flash:low heads `quick`; the head attribution wins over its
        # membership anywhere else.
        self.assertEqual(
            mixture_category_for("glm-5.3-flash", "low", parent_model="kimi-k3"),
            "quick",
        )

    def test_earliest_chain_position_beats_category_order(self):
        # A model that sits third in an earlier category but second in a
        # later one is labelled by the shallower fall-through slot: that is
        # the likelier route. The shipped chains no longer carry such a pair
        # (the 5.2 Ultrafast entry that did left on 2026-09-11), so the rule
        # is pinned on explicit chains.
        chains = {
            "unspecified-low": (("glm-5.3", "low"), ("deepseek-v4.1-flash", "low"), ("kimi-k3", "low")),
            "quick": (("glm-5.3-flash", "low"), ("kimi-k3", "low")),
        }
        self.assertEqual(
            mixture_category_for("kimi-k3", "low", parent_model="claude-opus-5", chains=chains),
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

    def test_every_head_labels_its_own_category_except_the_accepted_collisions(self):
        # A head shared by two categories labels only the earlier one in
        # canonical order. The owner accepted two such collisions on
        # 2026-10-13 -- (claude-opus-5-5, high) heads deep and
        # visual-engineering, (claude-opus-5-5, medium) heads writing and
        # capable -- and chose `max` for deep-work so its label survives.
        # Two more were accepted with the routing-recipe heads on 2026-10-28:
        # (gpt-6-astra, xhigh) heads ultrabrain and forensics, and
        # (claude-opus-5-5, xhigh) heads architect and synthesize, so those
        # two labels reach a child only through a route-provenance record.
        # Routing is unaffected; a fifth collision fails here by name.
        accepted = {
            "visual-engineering": "deep",
            "capable": "writing",
            "forensics": "ultrabrain",
            "synthesize": "architect",
        }
        for category, chain in HERMES_MIXTURE_CATEGORY_CHAINS.items():
            alias, effort = chain[0]
            with self.subTest(category=category):
                self.assertEqual(
                    mixture_category_for(alias, effort, parent_model=""),
                    accepted.get(category, category),
                )

    def test_a_membership_only_model_falls_back_to_its_first_chain(self):
        # Kimi K3.1 Pro at medium heads no chain and sits third in both
        # unspecified-high and writing (fourth in capable); the equal-position
        # tie goes to the first chain in canonical order. The earlier pin,
        # (claude-opus-5-5, medium), heads writing since 2026-10-13, so it is
        # no longer a membership-only model.
        self.assertEqual(
            mixture_category_for("kimi-k3.1-pro", "medium", parent_model="gpt-6-astra"),
            "unspecified-high",
        )

    def test_an_effort_that_matches_no_chain_entry_is_not_attributed(self):
        # Every category now declares its effort (owner decision), so a child
        # whose effort matches no entry — e.g. an inherited medium on the
        # quick chain's head — shows the bare model, not a routed category.
        self.assertEqual(
            mixture_category_for("glm-5.3-flash", "medium", parent_model="kimi-k3"),
            "",
        )

    def test_an_ultrafast_variant_projects_onto_its_base_models_category(self):
        # Providers serve some chain models through speed variants (e.g. the
        # OpenGateway Ultrafast tier: glm-5.3 via glm-5.3-ultrafast); the
        # variant projects onto the base model's category instead of leaving
        # the HUD row unlabeled. Kimi K3's tier lost its label with its base
        # model, which left the shipped chains on 2026-10-24.
        self.assertEqual(
            mixture_category_for("glm-5.3-ultrafast", "low", parent_model="gpt-5.6-sol"),
            "unspecified-low",
        )
        self.assertEqual(
            mixture_category_for("kimi-k3-ultrafast", "low", parent_model="gpt-5.6-sol"),
            "",
        )
        # An explicitly-named variant still matches itself first (no shipped
        # chain names a variant since 2026-09-11, so the rule is pinned on an
        # explicit chain).
        self.assertEqual(
            mixture_category_for(
                "kimi-k3-ultrafast", "low", parent_model="gpt-5.6-sol",
                chains={"quick": (("kimi-k3-ultrafast", "low"),)},
            ),
            "quick",
        )
        # The effort contract still applies to the base-model retry.
        self.assertEqual(
            mixture_category_for("kimi-k3-ultrafast", "max", parent_model="gpt-5.6-sol"),
            "",
        )

    def test_kimi_k31_pro_ids_are_priced_provider_mapped_and_chained(self):
        # Kimi K3.1 Pro took every Kimi K3 slot on 2026-10-24; the Highspeed
        # tier stays recognition-only. Both cost out at Moonshot's list price.
        cost = hermes_delegation_module._approximate_cost_usd
        self.assertEqual(cost("moonshotai/kimi-k3.1-pro", 1_000_000, 1_000_000, 0), 12.0)
        self.assertEqual(cost("kimi-k3.1-pro-highspeed", 1_000_000, 1_000_000, 0), 24.0)
        # Cached input is 0.20 on both cards: the default tenth on the base,
        # 0.05 of input on Highspeed, never a 2x multiplier.
        self.assertAlmostEqual(cost("kimi-k3.1-pro", 0, 1, 1_000_000), 0.20 + 10.0 / 1_000_000)
        self.assertAlmostEqual(cost("kimi-k3.1-pro-highspeed", 0, 1, 1_000_000), 0.20 + 20.0 / 1_000_000)
        self.assertIs(provider_serves_alias("kimi-k3.1-pro", "kimi-coding"), True)
        # Apitopia carried K3 but nobody observed it serving K3.1 Pro, so no
        # family is claimed for it and the vendor-specific verdict is False.
        self.assertIs(provider_serves_alias("kimi-k3.1-pro", "apitopia"), False)
        # OpenRouter relays every vendor, so its verdict stays unknown rather
        # than a claim; the family row matters for vendor-specific kinds.
        self.assertIsNone(provider_serves_alias("moonshotai/kimi-k3.1-pro", "openrouter"))
        self.assertIs(provider_serves_alias("kimi-k3.1-pro", "anthropic"), False)
        self.assertIs(provider_serves_alias("kimi-k3.1-pro-highspeed", "kimi-coding"), True)
        self.assertIs(provider_serves_alias("kimi-k3.1-pro-highspeed", "zai"), False)
        # The shipped slots label K3.1 Pro at the efforts K3 carried. Since
        # 2026-10-28 xhigh projects to review, where K3.1 Pro sits third
        # against fourth in architect (the shallower slot wins).
        for effort, category in (("xhigh", "review"), ("medium", "unspecified-high"), ("low", "quick")):
            with self.subTest(effort=effort):
                self.assertEqual(
                    mixture_category_for("moonshotai/kimi-k3.1-pro", effort, parent_model="gpt-6.1-sol"), category
                )
        # The retired generation and the Highspeed tier label nothing: an
        # exact contract never projects onto its base model's chain entry.
        for spelling in ("kimi-k3", "kimi-k3.1-pro-highspeed"):
            for effort in ("low", "medium", "high", "xhigh"):
                with self.subTest(spelling=spelling, effort=effort):
                    self.assertEqual(mixture_category_for(spelling, effort, parent_model="gpt-6.1-sol"), "")

    def test_gemini_4_argon_holds_the_gemini_slots_and_3_1_pro_labels_nothing(self):
        # Argon took every Gemini 3.1 Pro slot on 2026-10-28: it heads
        # google-search at `medium` and artistry at `high`, under every
        # spelling, and costs out at the introductory list price with the
        # 0.05 cache ratio. The retired id keeps its price and families for
        # an operator override but labels no category.
        cost = hermes_delegation_module._approximate_cost_usd
        for spelling in ("gemini-4-argon", "google/gemini-4-argon", "gemini-4-argon-2026-10-13"):
            with self.subTest(spelling=spelling):
                self.assertEqual(mixture_category_for(spelling, "medium", parent_model="gpt-6.1-sol"), "google-search")
                self.assertEqual(mixture_category_for(spelling, "high", parent_model="gpt-6.1-sol"), "artistry")
                self.assertAlmostEqual(cost(spelling, 1_000_000, 1_000_000, 1_000_000), 2.0 + 10.0 + 0.10)
                self.assertIs(provider_serves_alias(spelling, "google"), True)
                self.assertIs(provider_serves_alias(spelling, "anthropic"), False)
        for effort in ("medium", "high"):
            with self.subTest(retired_effort=effort):
                self.assertEqual(mixture_category_for("gemini-3.1-pro", effort, parent_model="gpt-6.1-sol"), "")
        self.assertAlmostEqual(cost("gemini-3.1-pro", 1_000_000, 1_000_000, 0), 14.0)
        self.assertIs(provider_serves_alias("gemini-3.1-pro", "google"), True)

    def test_gpt_61_terra_is_priced_and_provider_mapped_but_unchained(self):
        # Onboarded 2026-10-27 ahead of any chain placement: an operator chain
        # naming it costs out at OpenAI's list price and gets a provider
        # verdict, and it borrows no category label from GPT-6.1 Sol.
        cost = hermes_delegation_module._approximate_cost_usd
        for spelling in ("gpt-6.1-terra", "openai/gpt-6.1-terra", "gpt-6.1-terra-pro"):
            with self.subTest(spelling=spelling):
                self.assertEqual(cost(spelling, 1_000_000, 1_000_000, 0), 6.0)
                # Cached input is 5% of input, not the default tenth.
                self.assertAlmostEqual(cost(spelling, 0, 1, 1_000_000), 0.05 + 5.0 / 1_000_000)
        self.assertIs(provider_serves_alias("gpt-6.1-terra", "openai-codex"), True)
        # The declared `-pro` projection inherits the base row's eligibility.
        self.assertIs(provider_serves_alias("gpt-6.1-terra-pro", "openai-codex"), True)
        self.assertIs(provider_serves_alias("openai/gpt-6.1-terra-pro", "zai"), False)
        self.assertIs(provider_serves_alias("gpt-6.1-terra", "anthropic"), False)
        self.assertIsNone(provider_serves_alias("openai/gpt-6.1-terra", "openrouter"))
        for spelling in ("gpt-6.1-terra", "openai/gpt-6.1-terra", "gpt-6.1-terra-pro"):
            for effort in ("low", "medium", "high", "max"):
                with self.subTest(spelling=spelling, effort=effort):
                    self.assertEqual(mixture_category_for(spelling, effort, parent_model="gpt-6.1-sol"), "")
        chains = {"writing": (("gpt-6.1-terra", "medium"),)}
        self.assertEqual(
            mixture_category_for("gpt-6.1-terra", "medium", parent_model="gpt-6.1-sol", chains=chains), "writing"
        )

    # Catalog sync, 2026-10-28: (input, output, cached input) per MTok as the
    # vendor's own page lists it. Every id is recognition-only except Grok
    # 4.7, which the 2026-10-28 routing recipe placed at the x-search head.
    _CATALOG_SYNC_RATES = {
        "grok-4.7": (2.0, 6.0, 0.50),
        "grok-4.6": (2.0, 6.0, 0.50),
        "grok-4.5": (2.0, 6.0, 0.30),
        "grok-4.3": (1.25, 2.50, 0.20),
        "deepseek-v4-pro": (1.32, 3.96, 0.044),
        "gemini-3.8-flash": (0.75, 3.75, 0.075),
        "gemini-3.6-flash": (0.75, 3.75, 0.075),
        "gemini-3.5-flash-lite": (0.30, 2.50, 0.03),
        "glm-5.3-flashx": (0.37, 1.25, 0.075),
        # Alibaba publishes no per-model cache-hit rate: the default tenth.
        "qwen3.8-max": (2.0, 6.0, 0.20),
        "qwen3.8-flash": (0.15, 0.47, 0.015),
        "solar-pro4": (0.30, 1.20, 0.06),
        "minimax-m3": (0.30, 1.20, 0.06),
        "minimax-m3.1-flash": (0.15, 0.60, 0.015),
        # Corrected the same day (the old figures were GLM-4.x rates and a
        # halved ballpark of them); the tier carries its base's rate.
        "glm-5.2": (1.4, 4.4, 0.26),
        "glm-5.2-ultrafast": (1.4, 4.4, 0.26),
    }

    def test_catalog_sync_rows_cost_out_at_the_vendor_list_price(self):
        cost = hermes_delegation_module._approximate_cost_usd
        for model_id, (input_rate, output_rate, cached_rate) in self._CATALOG_SYNC_RATES.items():
            with self.subTest(model_id=model_id):
                self.assertEqual(
                    hermes_delegation_module.APPROX_PRICE_PER_MTOK[model_id], (input_rate, output_rate)
                )
                self.assertAlmostEqual(cost(model_id, 1_000_000, 1_000_000, 0), input_rate + output_rate)
                # Cached input lands on the vendor's cached rate to within the
                # table's three-significant-figure ratio (relative, so the
                # smallest cached rates are held as tightly as the largest).
                # One output token keeps the call non-empty (an empty call
                # returns no cost); its price is subtracted again.
                cached_cost = cost(model_id, 0, 1, 1_000_000) - output_rate / 1_000_000
                self.assertLessEqual(abs(cached_cost - cached_rate) / cached_rate, 0.005)
                # A provider-qualified spelling prices the same.
                self.assertEqual(
                    cost(f"vendor/{model_id}", 1_000, 1_000, 1_000), cost(model_id, 1_000, 1_000, 1_000)
                )
                # None of them borrows a category label from a chain, except
                # Grok 4.7, which heads x-search since 2026-10-28.
                self.assertEqual(
                    mixture_category_for(model_id, "high", parent_model="gpt-6.1-sol"),
                    "x-search" if model_id == "grok-4.7" else "",
                )

    def test_mixed_case_served_ids_meet_the_lower_case_price_rows(self):
        # MiniMax serves `MiniMax-M3` and `MiniMax-M3.1-Flash`; cost lookup
        # casefolds the id (and drops a provider segment) before it reads the
        # table, so the lower-case keys price the vendor's own spelling.
        cost = hermes_delegation_module._approximate_cost_usd
        for served, key in (
            ("MiniMax-M3", "minimax-m3"),
            ("minimax/MiniMax-M3", "minimax-m3"),
            ("MiniMax-M3.1-Flash", "minimax-m3.1-flash"),
        ):
            with self.subTest(served=served):
                self.assertNotIn(served, hermes_delegation_module.APPROX_PRICE_PER_MTOK)
                self.assertIsNotNone(cost(served, 1_000, 1_000, 1_000))
                self.assertEqual(cost(served, 1_000, 1_000, 1_000), cost(key, 1_000, 1_000, 1_000))

    def test_catalog_sync_provider_rows_answer_for_their_own_families_only(self):
        mapped = {
            "grok-4.7": "xai",
            "grok-4.6": "xai",
            "grok-4.5": "xai",
            "grok-4.3": "xai",
            "deepseek-v4-pro": "deepseek",
            "gemini-3.8-flash": "google",
            "gemini-3.6-flash": "gemini",
            "gemini-3.5-flash-lite": "google",
            "glm-5.3-flashx": "zai",
        }
        for model_id, family in mapped.items():
            with self.subTest(model_id=model_id):
                self.assertIs(provider_serves_alias(model_id, family), True)
                self.assertIs(provider_serves_alias(model_id, "anthropic"), False)
                # A multi-vendor relay serves everything, so its verdict stays
                # unknown rather than a claim either way.
                self.assertIsNone(provider_serves_alias(model_id, "openrouter"))
        # No OpenCode serving was observed for these two, so OpenCode is not
        # claimed in their rows (it is a relay, so its own verdict is unknown).
        for model_id in ("deepseek-v4-pro", "glm-5.3-flashx"):
            with self.subTest(model_id=model_id):
                self.assertNotIn(
                    "opencode", hermes_delegation_module.HERMES_MIXTURE_ALIAS_PROVIDER_FAMILIES[model_id]
                )
        # Qwen 3.8, Solar Pro 4, and MiniMax have no first-party family in the
        # vocabulary that was observed serving them. OpenRouter lists some of
        # these ids, but a relay-only row would turn every first-party
        # provider's verdict into False, so there is no row and the verdict
        # stays unknown.
        for model_id in ("qwen3.8-max", "qwen3.8-flash", "solar-pro4", "minimax-m3", "minimax-m3.1-flash"):
            with self.subTest(model_id=model_id):
                self.assertNotIn(model_id, hermes_delegation_module.HERMES_MIXTURE_ALIAS_PROVIDER_FAMILIES)
                self.assertIsNone(provider_serves_alias(model_id, "qwen-oauth"))
                self.assertIsNone(provider_serves_alias(model_id, "anthropic"))

    def test_the_access_gated_openai_models_are_priced_and_provider_mapped_but_unchained(self):
        # Onboarded 2026-11-06. OpenAI publishes a list price for each, so a
        # user who names one gets a cost; each borrows no category label from
        # the chain its base sits in; and only the families OpenAI names get
        # a provider verdict.
        cost = hermes_delegation_module._approximate_cost_usd
        for spelling, total in (
            ("gpt-6-cyber", 120.0),
            ("openai/gpt-6-cyber", 120.0),
            ("gpt-5.6-cyber", 87.5),
            ("gpt-6-rosalind", 90.0),
        ):
            with self.subTest(spelling=spelling):
                self.assertEqual(cost(spelling, 1_000_000, 1_000_000, 0), total)
                for effort in ("low", "medium", "xhigh", "max"):
                    self.assertEqual(mixture_category_for(spelling, effort, parent_model="gpt-6-astra"), "")
        self.assertIs(provider_serves_alias("gpt-6-cyber", "openai-codex"), True)
        self.assertIs(provider_serves_alias("gpt-6-cyber", "openai"), True)
        self.assertIs(provider_serves_alias("gpt-6-cyber", "openrouter"), None)
        self.assertIs(provider_serves_alias("gpt-6-cyber", "anthropic"), False)
        for model_id in ("gpt-5.6-cyber", "gpt-6-rosalind"):
            with self.subTest(model_id=model_id):
                self.assertIs(provider_serves_alias(model_id, "openai"), True)
                self.assertIs(provider_serves_alias(model_id, "openai-codex"), False)
        # An operator chain that names one still labels it.
        chains = {"ultrabrain": (("gpt-6-cyber", "xhigh"),)}
        self.assertEqual(
            mixture_category_for("gpt-6-cyber", "xhigh", parent_model="gpt-6-astra", chains=chains), "ultrabrain"
        )

    def test_the_recognition_only_third_party_rows_carry_the_vendor_list_price(self):
        # Onboarded 2026-11-06 from each vendor's own page: Z.ai's legal
        # sibling of GLM-5.3-FlashX, Mistral Large 4 under both of its API
        # spellings, and Upstage's Solar Mini 4. None has a provider row
        # except the Z.ai one, whose family the vocabulary names.
        cost = hermes_delegation_module._approximate_cost_usd
        for spelling, per_side in (
            ("glm-5.3-flashx-legal", (0.37, 1.25)),
            ("z-ai/glm-5.3-flashx-legal", (0.37, 1.25)),
            ("mistral-large-4", (0.70, 2.10)),
            ("mistralai/mistral-large-4-0", (0.70, 2.10)),
            ("solar-mini4", (0.10, 0.40)),
        ):
            with self.subTest(spelling=spelling):
                self.assertAlmostEqual(cost(spelling, 1_000_000, 1_000_000, 0), sum(per_side))
                self.assertEqual(mixture_category_for(spelling, "high", parent_model="gpt-6-astra"), "")
        # The legal sibling carries FlashX's cache ratio, not the default tenth.
        self.assertAlmostEqual(cost("glm-5.3-flashx-legal", 0, 1, 1_000_000), 0.37 * 0.203 + 1.25 / 1_000_000)
        self.assertIs(provider_serves_alias("glm-5.3-flashx-legal", "zai"), True)
        self.assertIs(provider_serves_alias("glm-5.3-flashx-legal", "openai"), False)
        for spelling in ("mistral-large-4", "solar-mini4"):
            with self.subTest(spelling=spelling):
                self.assertIsNone(provider_serves_alias(spelling, "openai"))
        # A Mistral id the vendor did not publish stays unpriced.
        self.assertEqual(cost("mistral-large-4-1", 1_000_000, 1_000_000, 0), None)

    def test_the_served_ultrafast_tiers_are_priced_without_a_provider_claim(self):
        # Observed 2026-09-24 on the OpenGateway route: the V4.1 Flash and GLM
        # 5.3 generations are served through Ultrafast tiers next to the base ids
        # the shipped chains already name. Neither tier is in a shipped chain,
        # so what a machine-level override naming one needs from the tables is a
        # price -- not a category label, and not a provider claim: no vendor
        # catalog lists either tier id (OpenRouter serves no `-ultrafast` id at
        # all), so the tables stay silent and the provider verdict stays unknown
        # rather than refusing a provider on a guess.
        cost = hermes_delegation_module._approximate_cost_usd
        for spelling in ("deepseek/deepseek-v4.1-flash-ultrafast", "deepseek-v4.1-flash-ultrafast"):
            with self.subTest(spelling=spelling):
                self.assertNotIn(
                    "deepseek-v4.1-flash-ultrafast",
                    hermes_delegation_module.HERMES_MIXTURE_ALIAS_PROVIDER_FAMILIES,
                )
                self.assertIsNone(provider_serves_alias(spelling, "deepseek"))
                self.assertIsNone(provider_serves_alias(spelling, "openrouter"))
                # The row mirrors the contract's documented rate, so a run on
                # the tier costs what a run on the contract costs -- cache reads
                # included, at the model's own 0.02 ratio rather than the
                # generic tenth.
                self.assertEqual(cost(spelling, 1_000_000, 1_000_000, 0), 1.5)
                self.assertEqual(
                    cost(spelling, 1_000, 1_000, 1_000_000),
                    cost("deepseek-v4.1-flash", 1_000, 1_000, 1_000_000),
                )
                # A serving tier is not the contract's second spelling, so the
                # chains' pointer slot (`deepseek-flash`) is not borrowed: the
                # tier stays bare instead of claiming a category it was not
                # routed to.
                self.assertEqual(mixture_category_for(spelling, "high", parent_model="kimi-k3"), "")
        for spelling in ("z-ai/glm-5.3-ultrafast", "glm-5.3-ultrafast"):
            with self.subTest(spelling=spelling):
                self.assertNotIn(
                    "glm-5.3-ultrafast",
                    hermes_delegation_module.HERMES_MIXTURE_ALIAS_PROVIDER_FAMILIES,
                )
                self.assertIsNone(provider_serves_alias(spelling, "zai"))
                # The row carries the generation's own documented list price.
                self.assertEqual(cost(spelling, 1_000_000, 1_000_000, 0), 5.8)
                # Cached input reads at GLM-5.3's own 0.186 ratio (docs.z.ai:
                # $0.26 cached vs $1.4 input) rather than the generic tenth,
                # and the tier prices a cached-input call identically to the
                # base model.
                self.assertAlmostEqual(cost("glm-5.3", 1_000, 1_000, 1_000_000), 0.2662)
                self.assertAlmostEqual(cost(spelling, 1_000, 1_000, 1_000_000), 0.2662)
                self.assertEqual(
                    cost(spelling, 1_000, 1_000, 1_000_000),
                    cost("glm-5.3", 1_000, 1_000, 1_000_000),
                )
                # And the shipped chains name only the base model, so the tier
                # projects onto the category its base sits in.
                self.assertEqual(mixture_category_for(spelling, "low", parent_model="kimi-k3"), "unspecified-low")
                self.assertEqual(mixture_category_for(spelling, "xhigh", parent_model="kimi-k3"), "")

    def test_a_routed_architect_child_is_labeled_architect(self):
        self.assertEqual(
            mixture_category_for("claude-fable-5-1", "xhigh", parent_model="kimi-k3"),
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
        # Per exact contract: (vendor prefix, effort, category, a serving
        # family, a non-serving family). Every declared alias inherits its
        # contract's category and provider eligibility.
        # The DeepSeek chains name the declared pointer (`deepseek-flash`),
        # so the exact id labels its category through the reverse
        # projection and the pointer through a direct chain match.
        # Since 2026-10-13: DeepSeek sits only at `low` (it left `deep`), and
        # (claude-opus-5-5, medium) heads writing -- capable shares that head
        # and loses the label to the earlier category (accepted collision).
        contracts = {
            "gpt-6-astra": ("openai", "xhigh", "ultrabrain", "openai", "anthropic"),
            "gpt-6.1-sol": ("openai", "high", "deep", "openai", "anthropic"),
            "deepseek-v4.1-flash": ("deepseek", "low", "swarm", "deepseek", "anthropic"),
            "claude-opus-5-5": ("anthropic", "medium", "writing", "anthropic", "openai"),
            "claude-sonnet-5-5": ("anthropic", "medium", "writing", "anthropic", "openai"),
            "claude-haiku-5-5": ("anthropic", "low", "simple-work", "anthropic", "openai"),
        }
        # A contract in no shipped chain, named by no provider-family row,
        # has nothing for its aliases to inherit. Jev is that case by
        # decision -- a non-generative model is never a chain member -- so it
        # is listed here rather than given invented chain metadata. Sonnet
        # 5.5 left this set on 2026-10-13, when the owner's table placed it.
        # GPT-6.1 Terra (onboarded 2026-10-27) is in no shipped chain yet; its
        # own test above checks pricing, provider eligibility, and `-pro`.
        # GPT-6 Cyber (2026-11-06) is access-gated and never chained; its own
        # test above checks the same three things.
        unchained = {"jev-1.13.0", "gpt-6.1-terra", "gpt-6-cyber"}
        for model_id in (*contracts, *expected):
            contract_id = expected.get(model_id, (model_id,))[0]
            if contract_id in unchained:
                continue
            vendor, effort, category, serving, non_serving = contracts[contract_id]
            requested = f"{vendor}/{model_id}"
            with self.subTest(model_id=model_id):
                self.assertEqual(
                    mixture_category_for(requested, effort, parent_model="kimi-k3"),
                    category,
                )
                self.assertIs(provider_serves_alias(requested, serving), True)
                self.assertIs(provider_serves_alias(requested, non_serving), False)

        # The unchained case, asserted rather than skipped: no category, and
        # an UNKNOWN provider verdict. Never False -- refusing a provider on
        # a guess is the failure `provider_serves_alias` exists to avoid, and
        # TypeSafe is not a family the shipped catalog has ever described.
        for spelling in ("jev-1.13.0", "jev-latest", "jev-preview", "typesafe/jev-1.13.0"):
            with self.subTest(model_id=spelling):
                self.assertEqual(mixture_category_for(spelling, "high", parent_model="kimi-k3"), "")
                self.assertIsNone(provider_serves_alias(spelling, "openai"))

        unknown = "openai/gpt-6-astra-pro-turbo"
        self.assertEqual(mixture_category_for(unknown, "xhigh", parent_model="kimi-k3"), "")
        self.assertIsNone(provider_serves_alias(unknown, "openai"))
        # Both DeepSeek spellings label the DeepSeek slots at their effort --
        # swarm since 2026-10-28, whose head it is; the vendor-routed legacy
        # id is not a declared alias and stays bare.
        for spelling in ("deepseek-flash", "deepseek/deepseek-v4.1-flash", "deepseek/deepseek-v4.1-flash-1017"):
            self.assertEqual(mixture_category_for(spelling, "low", parent_model="kimi-k3"), "swarm")
        # The 1017 spelling reaches the pointer because its declared row is the
        # pointer's own row; a mode or tier variant still does not.
        self.assertEqual(
            mixture_category_for(
                "deepseek/deepseek-v4.1-flash-1017", "low", parent_model="kimi-k3",
                chains={"swarm": (("deepseek-flash", "low"),)},
            ),
            "swarm",
        )
        self.assertEqual(mixture_category_for("deepseek/deepseek-v4-flash", "high", parent_model="kimi-k3"), "")

    def test_only_a_declared_row_equal_to_a_pointer_row_reaches_the_pointer(self):
        from unittest import mock

        candidates = hermes_delegation_module._model_alias_candidates
        shared = hermes_delegation_module._shared_model_aliases
        chains = {"swarm": (("deepseek-flash", "low"),)}
        self.assertIn("deepseek-flash", candidates("deepseek-v4.1-flash-1017"))
        # Hypothetical mode and tier variants of the same contract: declared
        # rows whose mode or tier differs from the pointer's never reach it.
        variants = {
            "deepseek-v4.1-flash-fast": ("deepseek-v4.1-flash", "thinking", "fast"),
            "deepseek-v4.1-flash-nothink": ("deepseek-v4.1-flash", "none", "standard"),
        }
        with mock.patch.dict(hermes_delegation_module.DECLARED_MODEL_ALIAS_PROJECTIONS, variants):
            for alias in variants:
                with self.subTest(alias=alias):
                    self.assertNotIn("deepseek-flash", candidates(alias))
                    self.assertEqual(
                        mixture_category_for(alias, "low", parent_model="kimi-k3", chains=chains), ""
                    )
        # The served-model attestation reads the same list: the pointer and
        # the snapshot it serves agree; another model or tier does not.
        self.assertTrue(shared("deepseek-flash", "deepseek-v4.1-flash-1017"))
        self.assertTrue(shared("deepseek-v4.1-flash-1017", "deepseek-flash"))
        for answering in ("deepseek-v4-pro", "deepseek-v4.1-flash-ultrafast", "deepseek-v4.1-flash-1118"):
            with self.subTest(answering=answering):
                self.assertEqual(shared("deepseek-v4.1-flash-1017", answering), [])
        self.assertEqual(shared("gpt-6-cyber", "gpt-6-astra"), [])

    def test_reverse_projection_is_limited_to_pointer_aliases(self):
        from omh.coding.model_contracts import EXACT_CONTRACT_POINTER_ALIASES as source_pointers

        pointers = hermes_delegation_module.EXACT_CONTRACT_POINTER_ALIASES
        exact = hermes_delegation_module.EXACT_MODEL_CONTRACT_ALIASES
        # Parity, and every pointer is a declared row at the contract's own
        # mode and tier — a second spelling, not a mode or price variant.
        self.assertEqual(pointers, source_pointers)
        for contract_id, aliases in pointers.items():
            self.assertIn(contract_id, exact)
            for alias in aliases:
                base, mode, tier = DECLARED_MODEL_ALIAS_PROJECTIONS[alias]
                self.assertEqual(base, contract_id)
                contract = MODEL_CONTRACTS[contract_id]
                self.assertEqual((mode, tier), (contract["reasoning_mode"], contract["service_tier"]))
        # A chain (shipped or an operator override) that names a mode or tier
        # variant never labels the base id: `-pro-flex` is a different
        # reasoning mode at half price, `-fast` is the same mode at double.
        for alias, effort in (("gpt-6-astra-pro-flex", "xhigh"), ("gpt-6-astra-fast", "low"), ("gpt-6-astra-pro", "xhigh")):
            chains = {"architect": ((alias, effort),)}
            with self.subTest(alias=alias):
                self.assertEqual(
                    mixture_category_for("openai/gpt-6-astra", effort, parent_model="kimi-k3", chains=chains), ""
                )
        # The forward direction stays: the variant itself matches its entry.
        self.assertEqual(
            mixture_category_for(
                "openai/gpt-6-astra-fast", "low", parent_model="kimi-k3",
                chains={"quick": (("gpt-6-astra-fast", "low"),)},
            ),
            "quick",
        )

    def test_dated_snapshot_mirror_stays_in_parity_with_core(self) -> None:
        from omh.coding import model_contracts

        self.assertEqual(
            hermes_delegation_module._DATED_SNAPSHOT_SUFFIX.pattern,
            model_contracts._DATED_SNAPSHOT_SUFFIX.pattern,
        )
        for form in (
            "gpt-5.6-terra-2026-07-09",
            "openai/gpt-5.6-terra-2026-07-09",
            "GPT-6-Astra-2026-08-01",
            "deepseek/deepseek-flash-2026-09-01",
            "gpt-6-astra-2026-13-01",
            "gpt-6-astra-20260801",
            "gpt-6-astra-2026-08-01-fast",
            "gpt-6-astra",
            "",
        ):
            with self.subTest(form=form):
                self.assertEqual(
                    hermes_delegation_module._dated_snapshot_base(form),
                    model_contracts.dated_snapshot_base(form),
                )

    def test_dated_snapshot_labels_its_base_category_price_and_provider(self) -> None:
        # GPT-6.1 Sol sits in the shipped deep chain; a provider that serves only
        # a dated id (a shape reported for GPT-5.6 Terra on 2026-09-11; Terra
        # left the shipped chains on 2026-09-23) must label the same category,
        # price, and provider family as the base, while an unknown base with a
        # date gains nothing.
        for spelling in ("gpt-6.1-sol-2026-09-29", "openai/gpt-6.1-sol-2026-09-29"):
            with self.subTest(spelling=spelling):
                self.assertEqual(
                    mixture_category_for(spelling, "high", parent_model="kimi-k3"),
                    mixture_category_for("gpt-6.1-sol", "high", parent_model="kimi-k3"),
                )
                self.assertEqual(mixture_category_for(spelling, "high", parent_model="kimi-k3"), "deep")
                self.assertEqual(
                    hermes_delegation_module._approximate_cost_usd(spelling, 1000.0, 1000.0, 100.0),
                    hermes_delegation_module._approximate_cost_usd("gpt-6.1-sol", 1000.0, 1000.0, 100.0),
                )
                self.assertIs(provider_serves_alias(spelling, "openai"), True)
                self.assertIs(provider_serves_alias(spelling, "anthropic"), False)
        # A snapshot of the exact id reaches the served pointer the chain names
        # (the swarm head since 2026-10-28).
        self.assertEqual(
            mixture_category_for("deepseek/deepseek-v4.1-flash-2026-09-01", "low", parent_model="kimi-k3"),
            "swarm",
        )
        # The exact-contract label follows the snapshot too.
        self.assertEqual(
            mixture_category_for("gpt-6-astra-2026-08-01", "xhigh", parent_model="kimi-k3"),
            mixture_category_for("gpt-6-astra", "xhigh", parent_model="kimi-k3"),
        )
        # A child on a dated snapshot of the parent's model is on the parent's
        # model; the parent's own id is the base the reader knows, so this
        # holds for an alias no table describes as well.
        self.assertEqual(
            mixture_category_for("gpt-6.1-sol-2026-09-29", "high", parent_model="gpt-6.1-sol"), "inherit"
        )
        self.assertEqual(
            mixture_category_for("zzz-mystery-2026-08-01", "high", parent_model="zzz-mystery"), "inherit"
        )
        # One direction only, like the resolver's explicit match: an unpinned
        # child under a date-pinned parent, or a different date, is not the
        # parent's run and falls through to the chain match.
        self.assertEqual(
            mixture_category_for("gpt-6.1-sol", "high", parent_model="openai/gpt-6.1-sol-2026-09-29"), "deep"
        )
        self.assertEqual(
            mixture_category_for("gpt-6.1-sol-2026-10-01", "high", parent_model="gpt-6.1-sol-2026-09-29"), "deep"
        )
        self.assertEqual(
            mixture_category_for("zzz-mystery-2026-08-01", "high", parent_model="zzz-mystery-2026-07-09"), ""
        )
        # Bounds: an unknown base, a non-trailing date, and a compact shape.
        for spelling in ("gpt-7-nova-2026-07-09", "gpt-6.1-sol-2026-09-29-fast", "gpt-6.1-sol-20260922"):
            with self.subTest(spelling=spelling):
                self.assertEqual(mixture_category_for(spelling, "high", parent_model="kimi-k3"), "")
                self.assertIsNone(provider_serves_alias(spelling, "openai"))
                self.assertIsNone(hermes_delegation_module._approximate_cost_usd(spelling, 1000.0, 1000.0, 0.0))


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
                effective_mixture_category_chains(tmp, Path(tmp) / "hermes"), HERMES_MIXTURE_CATEGORY_CHAINS
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
                effective_mixture_category_chains(tmp, Path(tmp) / "hermes"), HERMES_MIXTURE_CATEGORY_CHAINS
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
            chains = effective_mixture_category_chains(tmp, Path(tmp) / "hermes")
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
                    effective_mixture_category_chains(tmp, Path(tmp) / "hermes"),
                    HERMES_MIXTURE_CATEGORY_CHAINS,
                )

    def test_named_provider_tokens_apply_across_routing_documents(self):
        token = "custom:cli-proxy"
        self.assertTrue(is_provider_id_token(token))
        self.assertEqual(parse_mixture_chain_overrides({
            "schema_version": "mixture_chain_overrides/v1",
            "categories": {"quick": [{"model": token, "reasoning_effort": "low"}]},
        }), ({"quick": ((token, "low"),)}, "applied"))
        routes, status = parse_model_provider_routes({
            "schema_version": "model_provider_routes/v1",
            "models": {token: {"provider": token, "model": token}},
        })
        self.assertEqual((routes, status), ({token: (token, token)}, "applied"))
        entitlements, status = parse_provider_entitlements({
            "schema_version": "provider_entitlements/v1", "providers": {token: "gateway"},
        })
        self.assertEqual(status, "applied")
        self.assertEqual(entitlements["providers"], {token: "gateway"})
        self.assertEqual(parse_model_price_overrides({
            "schema_version": "model_price_overrides/v1",
            "models": {token: {"input_per_mtok": 1, "output_per_mtok": 2}},
        })[1], "applied")

        for invalid in ("custom: cli-proxy", "custom:", "custom::cli-proxy", "custom:cli-proxy!", "a" * 129):
            with self.subTest(invalid=invalid):
                self.assertFalse(is_provider_id_token(invalid))
                self.assertTrue(parse_model_provider_routes({
                    "schema_version": "model_provider_routes/v1",
                    "models": {"safe": {"provider": invalid, "model": "safe"}},
                })[1].startswith("invalid:"))
        self.assertTrue(is_provider_id_token("a" * 128))
        # An effort stays a bare word: the colon admitted for model and
        # provider ids would make `model:effort` text ambiguous.
        self.assertTrue(parse_mixture_chain_overrides({
            "schema_version": "mixture_chain_overrides/v1",
            "categories": {"quick": [{"model": "kimi-k3", "reasoning_effort": "x:high"}]},
        })[1].startswith("invalid:"))

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

    def test_a_child_labels_its_own_row_from_the_prompt_it_was_opened_with(self):
        """The label the manifest cannot supply, from a source that proves ownership.

        A manifest names no session, so in session scope it is dropped and the
        row loses its label. A child's first user row is IN that child's
        session, so attributing it is a primary key rather than a timestamp
        guess — and the sentence is the same sentence, since the manifest's
        `goal` is also the dispatch prompt.
        """
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260818_100100_opened",
                    "model": "deepseek/deepseek-flash",
                    "started_at": NOW - 30,
                    "messages": [("user", "Implement the cost engine for jeval"), ("assistant", "working")],
                },
                {
                    "id": "20260818_100100_silent",
                    "model": "deepseek/deepseek-flash",
                    "started_at": NOW - 30,
                },
            ],
        )

        rows = {
            row["task_id"]: row
            for row in read_hermes_native_subagents(
                self.home, now=NOW, omh_home=self.home / ".omh", session_ref=PARENT_ID
            )["rows"]
        }

        self.assertEqual(rows["opened"]["action"], "Implement the cost engine for jeval")
        # No first user row is the honest empty label, not a fabricated one.
        self.assertEqual(rows["silent"]["action"], "")

    def test_the_opening_prompt_never_outranks_an_attributed_manifest_goal(self):
        """Mutation guard: the fallback is a fallback, not a replacement."""
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260818_100100_opened",
                    "model": "deepseek/deepseek-flash",
                    "started_at": NOW - 30,
                    "messages": [("user", "the prompt this child was opened with")],
                },
            ],
        )
        _write_manifest(self.home, "deleg_owned", ["the goal the manifest attributed"], started=NOW - 32, log_mtime=NOW)

        rows = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home / ".omh")["rows"]

        self.assertEqual(rows[0]["action"], "the goal the manifest attributed")

    def test_a_long_opening_prompt_is_cut_to_the_same_limit_a_goal_is(self):
        """Pins the RENDER limit only.

        The reader truncates again when it reads, to bound what it holds, and
        that inner cut is invisible from a row because the row applies the
        same limit. Removing it does not fail this test and is disclosed
        rather than covered by an assertion that cannot see it.
        """
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260818_100100_opened",
                    "model": "deepseek/deepseek-flash",
                    "started_at": NOW - 30,
                    "messages": [("user", "x" * 400)],
                },
            ],
        )

        rows = read_hermes_native_subagents(
            self.home, now=NOW, omh_home=self.home / ".omh", session_ref=PARENT_ID
        )["rows"]

        self.assertLessEqual(len(rows[0]["action"]), _ACTION_LIMIT)

    def test_provider_wire_child_uses_configured_alias_and_provider(self):
        route_path = self.home / "routing" / "model-providers.json"
        route_path.parent.mkdir(parents=True)
        route_path.write_text(
            json.dumps(
                {
                    "schema_version": "model_provider_routes/v1",
                    "models": {
                        "kimi-k3.1-pro": {
                            "provider": "gateway",
                            "model": "moonshotai/kimi-k3.1-pro",
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
                    "model": "moonshotai/kimi-k3.1-pro",
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

        self.assertEqual(row["alias"], "kimi-k3.1-pro")
        self.assertEqual(row["provider"], "gateway")
        self.assertEqual(row["provider_source"], "model_provider_routes")
        self.assertEqual(row["model"], "moonshotai/kimi-k3.1-pro")
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
        # 10k input @ $4/M + 30k cache reads @ a tenth of input + 4k output
        # @ $20/M.
        self.assertTrue(row["cost_approximate"])
        self.assertAlmostEqual(
            row["cost_usd"],
            (10_000 * 4.0 + 30_000 * 0.40 + 4_000 * 20.0) / 1_000_000,
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

    def test_the_hosts_no_pricing_sentinel_is_approximated_like_an_absence(self):
        # Given: a child served by a custom gateway provider. Hermes has no
        # rate for it, so its pricing returns no amount and stamps its own
        # `unknown` no-figure status (`agent/usage_pricing.py:549`, persisted
        # by `agent/turn_usage.py:236,257`) -- the host saying it has NO
        # figure, not a billing outcome.
        _build_state_db(
            self.home,
            [{
                "id": "20260818_100100_gateway1",
                "model": "anthropic/claude-fable-5-1",
                "started_at": NOW - 60,
                "usage": {
                    "input_tokens": 10_000,
                    "output_tokens": 4_000,
                    "actual_cost_usd": 0.0,
                    "cost_status": "unknown",
                    "cost_source": "none",
                    "last_seen": NOW - 5,
                },
            }],
        )
        _write_manifest(self.home, "deleg_gw", ["gateway lane"], started=NOW - 65, log_mtime=NOW - 5)
        # When: the reader projects the child
        row = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home)["rows"][0]
        # Then: the token-derived figure fires exactly as it does for a row
        # with no provenance at all. Fable 5.1 lists $10/M input, $50/M
        # output, cache reads at $0.25/M.
        self.assertTrue(row["cost_approximate"])
        self.assertAlmostEqual(
            row["cost_usd"], (10_000 * 10.0 + 4_000 * 50.0) / 1_000_000
        )
        # And: the host's own words stay on the row as recorded -- OMH
        # reports what the host wrote, it does not rewrite it.
        self.assertEqual(row["cost_status"], "unknown")
        self.assertEqual(row["cost_source"], "none")

    def test_an_unpriceable_sentinel_keeps_the_zero_the_host_can_render(self):
        # Given: the same no-pricing sentinel on a model OMH has no rate for
        _build_state_db(
            self.home,
            [{
                "id": "20260818_100100_gateway2",
                "model": "og/some-unlisted-model",
                "started_at": NOW - 60,
                "usage": {
                    "input_tokens": 10_000,
                    "output_tokens": 4_000,
                    "actual_cost_usd": 0.0,
                    "cost_status": "unknown",
                    "cost_source": "none",
                    "last_seen": NOW - 5,
                },
            }],
        )
        _write_manifest(self.home, "deleg_gw2", ["gateway lane"], started=NOW - 65, log_mtime=NOW - 5)
        # When: the reader projects the child
        row = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home)["rows"][0]
        # Then: nothing is invented and nothing is taken away -- the row
        # renders exactly as it did before this rule existed,
        # `$0.0000 (unknown)`. Only a SUCCESSFUL approximation changes it.
        self.assertEqual(row["cost_usd"], 0.0)
        self.assertNotIn("cost_approximate", row)
        self.assertEqual(row["cost_status"], "unknown")
        self.assertEqual(row["cost_source"], "none")

    def test_one_informative_row_stops_the_sentinel_approximation(self):
        # Given: a group that mixes the host's no-pricing sentinel with one
        # row that DID record a billing outcome, and whose summed cost is
        # still zero. MAX(cost_status) over this group answers "unknown",
        # which is exactly the reduction a per-row count has to survive.
        _build_state_db(
            self.home,
            [{
                "id": "20260818_100100_mixedsen",
                "model": "gpt-5.6-sol",
                "started_at": NOW - 60,
                "usages": [
                    {
                        "input_tokens": 10_000,
                        "output_tokens": 4_000,
                        "actual_cost_usd": 0.0,
                        "cost_status": "unknown",
                        "cost_source": "none",
                        "first_seen": NOW - 55,
                        "last_seen": NOW - 30,
                    },
                    {
                        "input_tokens": 5_000,
                        "output_tokens": 1_000,
                        "actual_cost_usd": 0.0,
                        "cost_status": "included",
                        "cost_source": "subscription",
                        "first_seen": NOW - 25,
                        "last_seen": NOW - 5,
                    },
                ],
            }],
        )
        _write_manifest(self.home, "deleg_ms", ["mixed lane"], started=NOW - 65, log_mtime=NOW - 5)
        # When: the reader projects the child
        row = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home)["rows"][0]
        # Then: the confirmed zero stands. One row vouching for the figure
        # is enough, whatever the other rows recorded.
        self.assertEqual(row["cost_usd"], 0.0)
        self.assertNotIn("cost_approximate", row)
        # And: the WORD the surface renders is the one that vouched for the
        # zero. A plain MAX answers alphabetically, which put "unknown"
        # ahead of "included" and made a vouched zero read as unpriced.
        self.assertEqual(row["cost_status"], "included")
        self.assertEqual(row["cost_source"], "subscription")

    def test_an_empty_session_model_is_filled_from_the_observed_usage_model(self):
        # Given: a child whose `sessions.model` is empty -- the row was
        # created before the model was known -- while its usage rows record
        # the model every call actually ran on
        _build_state_db(
            self.home,
            [{
                "id": "20260818_100100_nomodel1",
                "model": "",
                "effort": "high",
                "started_at": NOW - 60,
                "usage": {
                    "model": "claude-fable-5-1",
                    "input_tokens": 10_000,
                    "output_tokens": 4_000,
                    "last_seen": NOW - 5,
                },
            }],
        )
        _write_manifest(self.home, "deleg_nm", ["unnamed lane"], started=NOW - 65, log_mtime=NOW - 5)
        # When: the reader projects the child
        row = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home)["rows"][0]
        # Then: the label names the observed model instead of the bare
        # `:high` the empty recording used to produce, and everything keyed
        # off the model follows it -- category here, and pricing below.
        self.assertEqual(row["model"], "claude-fable-5-1")
        self.assertEqual(row["effort"], "high")
        self.assertEqual(row["category"], "visual-engineering")
        self.assertTrue(row["cost_approximate"])

    def test_two_observed_usage_models_leave_an_empty_model_untouched(self):
        # The negative control: a child whose usage rows name two models has
        # no single answer, so the row stays exactly as recorded. Nothing is
        # inferred from the parent -- Hermes does not copy its model down.
        _build_state_db(
            self.home,
            [{
                "id": "20260818_100100_twomodel",
                "model": "",
                "started_at": NOW - 60,
                "usages": [
                    {"model": "claude-fable-5-1", "output_tokens": 10, "last_seen": NOW - 20},
                    {"model": "gpt-5.6-sol", "output_tokens": 10, "last_seen": NOW - 5},
                ],
            }],
        )
        row = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home)["rows"][0]
        self.assertEqual(row["model"], "")
        self.assertEqual(row["category"], "")

    def test_a_recorded_session_model_wins_over_the_usage_model(self):
        # The session row is the child's own identity when it has one; the
        # usage fill only covers the absence.
        _build_state_db(
            self.home,
            [{
                "id": "20260818_100100_ownmodel",
                "model": "claude-fable-5-1",
                "started_at": NOW - 60,
                "usage": {"model": "gpt-5.6-sol", "output_tokens": 10, "last_seen": NOW - 5},
            }],
        )
        row = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home)["rows"][0]
        self.assertEqual(row["model"], "claude-fable-5-1")

    def test_an_unrouted_child_shows_the_provider_the_host_billed_it_under(self):
        # Given: a wire model no `model-providers.json` row names, whose
        # usage the host recorded against a billing provider
        _build_state_db(
            self.home,
            [{
                "id": "20260818_100100_billprov",
                "model": "anthropic/claude-fable-5-1",
                "started_at": NOW - 60,
                "usage": {
                    "billing_provider": "og",
                    "output_tokens": 10,
                    "last_seen": NOW - 5,
                },
            }],
        )
        # When: the reader projects the child
        row = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home)["rows"][0]
        # Then: the provider column shows the observed billing provider,
        # marked with the origin that earned it rather than passed off as
        # OMH's own configuration.
        self.assertEqual(row["provider"], "og")
        self.assertEqual(row["provider_source"], "hermes_billing_provider")

    def test_two_billing_providers_leave_the_provider_column_empty(self):
        # The negative control: a session billed under two providers has no
        # single answer, and a guessed one would be worse than none.
        _build_state_db(
            self.home,
            [{
                "id": "20260818_100100_twoprovs",
                "model": "anthropic/claude-fable-5-1",
                "started_at": NOW - 60,
                "usages": [
                    {"billing_provider": "og", "output_tokens": 10, "last_seen": NOW - 20},
                    {"billing_provider": "custom", "output_tokens": 10, "last_seen": NOW - 5},
                ],
            }],
        )
        row = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home)["rows"][0]
        self.assertEqual(row["provider"], "")
        self.assertNotIn("provider_source", row)

    def test_one_billing_provider_beside_an_unattributed_row_is_still_one(self):
        # The column defaults to the empty string, so a session with one
        # attributed row and one unattributed row must not read as two
        # providers -- there is exactly one, and it is the one to show.
        _build_state_db(
            self.home,
            [{
                "id": "20260818_100100_oneprov1",
                "model": "anthropic/claude-fable-5-1",
                "started_at": NOW - 60,
                "usages": [
                    {"billing_provider": "og", "output_tokens": 10, "last_seen": NOW - 20},
                    {"billing_provider": "", "output_tokens": 10, "last_seen": NOW - 5},
                ],
            }],
        )
        row = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home)["rows"][0]
        self.assertEqual(row["provider"], "og")
        self.assertEqual(row["provider_source"], "hermes_billing_provider")

    def test_the_no_figure_status_is_the_test_whatever_source_it_carries(self):
        # Hermes stamps `unknown` whenever its pricing produced no amount,
        # and a partially-rated route pairs that status with an informative
        # source instead of `none`. The STATUS is what says "no figure", so
        # the source must not rescue it into a vouched zero.
        _build_state_db(
            self.home,
            [{
                "id": "20260818_100100_partial1",
                "model": "gpt-5.6-sol",
                "started_at": NOW - 60,
                "usage": {
                    "input_tokens": 10_000,
                    "output_tokens": 4_000,
                    "actual_cost_usd": 0.0,
                    "cost_status": "unknown",
                    "cost_source": "litellm",
                    "last_seen": NOW - 5,
                },
            }],
        )
        _write_manifest(self.home, "deleg_pr", ["partial lane"], started=NOW - 65, log_mtime=NOW - 5)
        row = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home)["rows"][0]
        self.assertTrue(row["cost_approximate"])
        self.assertGreater(row["cost_usd"], 0.0)
        self.assertEqual(row["cost_status"], "unknown")
        self.assertEqual(row["cost_source"], "litellm")

    def test_a_configured_route_still_wins_over_the_billing_provider(self):
        # The other negative control: OMH's own configuration is the answer
        # whenever it has one, so the fallback never overrides a route.
        route_path = self.home / "routing" / "model-providers.json"
        route_path.parent.mkdir(parents=True)
        route_path.write_text(
            json.dumps(
                {
                    "schema_version": "model_provider_routes/v1",
                    "models": {
                        "fable": {"provider": "gateway", "model": "anthropic/claude-fable-5-1"}
                    },
                }
            ),
            encoding="utf-8",
        )
        _build_state_db(
            self.home,
            [{
                "id": "20260818_100100_routewin",
                "model": "anthropic/claude-fable-5-1",
                "started_at": NOW - 60,
                "usage": {"billing_provider": "og", "output_tokens": 10, "last_seen": NOW - 5},
            }],
        )
        row = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home)["rows"][0]
        self.assertEqual(row["provider"], "gateway")
        self.assertEqual(row["provider_source"], "model_provider_routes")

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

    def test_an_ended_child_reads_done_inside_the_recent_window_with_elapsed_to_its_end(self):
        # The live row: started 1791946029.16, ended 1791946032.19 with
        # `agent_close`, and drawn running in the HUD's agent panel for the
        # next 150 s while the TUI's agent strip already showed it done.
        for scope in (None, PARENT_ID):
            with self.subTest(session_ref=scope):
                _build_state_db(
                    self.home,
                    [
                        {
                            "id": "20260818_100100_ended1",
                            "model": "gpt-5.6-sol",
                            "started_at": NOW - 40,
                            "ended_at": NOW - 37,
                            "end_reason": "agent_close",
                            "usage": {"first_seen": NOW - 39, "last_seen": NOW - 38, "output_tokens": 12},
                        }
                    ],
                    include_end_columns=True,
                )
                payload = read_hermes_native_subagents(
                    self.home, now=NOW, omh_home=self.home / ".omh", session_ref=scope
                )
                (self.home / "state.db").unlink()
                (row,) = payload["rows"]
                self.assertEqual(row["state"], "done")
                self.assertEqual(row["elapsed_seconds"], 3.0)
                self.assertEqual((payload["running"], payload["completed"]), (0, 1))

    def test_an_ended_childs_elapsed_stops_at_its_end_when_its_log_moved_later(self):
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260818_100100_ended3",
                    "model": "gpt-5.6-sol",
                    "started_at": NOW - 40,
                    "ended_at": NOW - 37,
                    "end_reason": "agent_close",
                    "usage": {"last_seen": NOW - 38, "output_tokens": 12},
                }
            ],
            include_end_columns=True,
        )
        _write_manifest(self.home, "deleg_ended3", ["late log"], started=NOW - 41, log_mtime=NOW - 20)
        (row,) = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home / ".omh")["rows"]
        self.assertEqual(row["state"], "done")
        self.assertEqual(row["elapsed_seconds"], 3.0)

    def test_an_ended_child_without_model_usage_reads_failed(self):
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260818_100100_ended2",
                    "model": "gpt-5.6-sol",
                    "started_at": NOW - 40,
                    "ended_at": NOW - 37,
                    "end_reason": "agent_close",
                }
            ],
            include_end_columns=True,
        )
        (row,) = read_hermes_native_subagents(
            self.home, now=NOW, omh_home=self.home / ".omh", session_ref=PARENT_ID
        )["rows"]
        self.assertEqual(row["state"], "failed")
        self.assertEqual(row["failure_hint"], "no model usage observed")

    def test_an_unended_recent_child_still_reads_running(self):
        for include_end_columns in (True, False):
            with self.subTest(include_end_columns=include_end_columns):
                _build_state_db(
                    self.home,
                    [
                        {
                            "id": "20260818_100100_open01",
                            "model": "gpt-5.6-sol",
                            "started_at": NOW - 40,
                            "usage": {"last_seen": NOW - 5, "output_tokens": 12},
                        }
                    ],
                    include_end_columns=include_end_columns,
                )
                payload = read_hermes_native_subagents(
                    self.home, now=NOW, omh_home=self.home / ".omh", session_ref=PARENT_ID
                )
                (self.home / "state.db").unlink()
                (row,) = payload["rows"]
                self.assertEqual(row["state"], "running")
                self.assertEqual(row["elapsed_seconds"], 40.0)

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


class ServedModelAttestationTest(unittest.TestCase):
    """The model a child asked for, compared against the one that answered.

    `session_model_usage.model` is written per call from the model that
    answered. The request is read from the child's own records: the `Model:`
    line of the identity trailer Hermes stored with its first system prompt,
    written before the first call. Hermes rewrites that stored prompt from the
    running model at an in-place compaction and at a later turn's start, so it
    is read only from a first segment with no archived message and at most one
    user message. `sessions.model` is not enough on its own, because Hermes
    rewrites it to the first accounted call's model, so it can show a
    disagreement but never attest agreement.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)

    def _attestation(self, child: dict, **build) -> dict:
        build.setdefault("include_prompt_columns", True)
        _build_state_db(self.home, [child], **build)
        payload = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home / ".omh")
        return payload["rows"][0]["model_attestation"]

    def test_an_attested_request_the_answer_matches_attests_agreement(self):
        attestation = self._attestation(
            {
                "id": "20260818_100100_agree1",
                "model": "claude-fable-5-1",
                "prompt_model": "claude-fable-5-1",
                "started_at": NOW - 60,
                "usage": {"model": "claude-fable-5-1", "output_tokens": 10, "last_seen": NOW - 5},
            }
        )
        self.assertEqual(attestation["verdict"], "agreement")
        self.assertEqual(attestation["basis"], "resolved_match")
        self.assertEqual(attestation["requested"], "claude-fable-5-1")
        self.assertEqual(attestation["answering"], "claude-fable-5-1")
        self.assertEqual(attestation["requested_source"], "prompt_identity")

    def test_a_first_call_substitution_the_session_row_hides_attests_disagreement(self):
        # The shape Hermes leaves behind (`first_accounted_route`): the child
        # asked for gpt-6-astra, its first call was answered by
        # claude-fable-5-1 under a billing provider, and Hermes rewrote
        # `sessions.model` to the answer. With one turn and no compaction the
        # stored prompt still names the request, so this is a substitution,
        # not an agreement.
        attestation = self._attestation(
            {
                "id": "20260818_100100_hidden1",
                "model": "claude-fable-5-1",
                "prompt_model": "gpt-6-astra",
                "started_at": NOW - 60,
                "usage": {
                    "model": "claude-fable-5-1",
                    "billing_provider": "openrouter",
                    "output_tokens": 10,
                    "last_seen": NOW - 5,
                },
            }
        )
        self.assertEqual(attestation["verdict"], "disagreement")
        self.assertEqual(attestation["basis"], "resolved_mismatch")
        self.assertEqual(attestation["requested"], "gpt-6-astra")
        self.assertEqual(attestation["requested_source"], "prompt_identity")
        self.assertEqual(attestation["answering"], "claude-fable-5-1")

    def test_an_unattested_session_model_that_agrees_is_unknown_not_agreement(self):
        # No stored prompt names the request, and the session row agrees with
        # the answer. That row may be the answer itself, so the verdict says
        # it cannot tell, and does not name the row `requested`.
        attestation = self._attestation(
            {
                "id": "20260818_100100_noattst",
                "model": "claude-fable-5-1",
                "started_at": NOW - 60,
                "usage": {
                    "model": "claude-fable-5-1",
                    "billing_provider": "openrouter",
                    "output_tokens": 10,
                    "last_seen": NOW - 5,
                },
            }
        )
        self.assertEqual(attestation["verdict"], "unknown")
        self.assertEqual(attestation["basis"], "requested_model_not_attested")
        self.assertEqual(attestation["answering"], "claude-fable-5-1")
        self.assertNotIn("requested", attestation)
        self.assertNotIn("requested_source", attestation)
        self.assertNotIn("resolved", attestation)

    def test_an_unattested_session_model_that_disagrees_still_attests_disagreement(self):
        # Hermes only ever copies an accounted call's model into the row, so a
        # row that differs from the sole answering model was not copied from
        # it. That disagreement stays detectable without a stored prompt. Both
        # sides are named RESOLVED -- the vendor prefix the usage row carried
        # is not what the reader reports.
        attestation = self._attestation(
            {
                "id": "20260818_100100_swap1",
                "model": "gpt-6-astra",
                "started_at": NOW - 60,
                "usage": {
                    "model": "anthropic/claude-fable-5-1",
                    "output_tokens": 10,
                    "last_seen": NOW - 5,
                },
            }
        )
        self.assertEqual(attestation["verdict"], "disagreement")
        self.assertEqual(attestation["basis"], "resolved_mismatch")
        self.assertEqual(attestation["requested"], "gpt-6-astra")
        self.assertEqual(attestation["requested_source"], "session_model")
        self.assertEqual(attestation["answering"], "claude-fable-5-1")

    def test_a_compression_continuation_prompt_attests_nothing(self):
        # A continuation row's parent is the previous segment, not the
        # delegating session, and its prompt was rebuilt from whatever model
        # ran at compaction, which can be a fallback. Its trailer is ignored.
        attestation = self._attestation(
            {
                "id": "20260818_100100_contin1",
                "model": "claude-fable-5-1",
                "prompt_model": "claude-fable-5-1",
                "parent_session_id": "20260818_100050_segment",
                "started_at": NOW - 60,
                "usage": {"model": "claude-fable-5-1", "output_tokens": 10, "last_seen": NOW - 5},
            }
        )
        self.assertEqual(attestation["verdict"], "unknown")
        self.assertEqual(attestation["basis"], "requested_model_not_attested")

    def test_an_in_place_compaction_withholds_the_stored_request(self):
        # Hermes' default compaction keeps the session id: it archives the
        # compacted rows (`active = 0`) and stores a prompt rebuilt for the
        # RUNNING model, which after a fallback is the fallback. This child
        # asked for gpt-6-astra, claude-fable-5-1 answered, and the rebuilt
        # trailer now names the answer. It must not read as an agreement.
        attestation = self._attestation(
            {
                "id": "20260818_100100_inplace",
                "model": "claude-fable-5-1",
                "prompt_model": "claude-fable-5-1",
                # One user message in all, so only the archived row can
                # withhold the prompt here.
                "archived_messages": [("user", "the delegated goal")],
                "messages": [("assistant", "[compaction summary]")],
                "started_at": NOW - 60,
                "usage": {
                    "model": "claude-fable-5-1",
                    "billing_provider": "openrouter",
                    "output_tokens": 10,
                    "last_seen": NOW - 5,
                },
            }
        )
        self.assertEqual(attestation["verdict"], "unknown")
        self.assertEqual(attestation["basis"], "requested_model_prompt_may_be_rebuilt")
        self.assertNotIn("requested", attestation)
        self.assertNotIn("requested_source", attestation)

    def test_a_later_turn_withholds_the_stored_request(self):
        # A turn after the first rebuilds and stores the prompt when its
        # identity differs from the running model (a child's output-schema
        # retry is a second turn). Two user messages mean it may have.
        attestation = self._attestation(
            {
                "id": "20260818_100100_retry11",
                "model": "claude-fable-5-1",
                "prompt_model": "claude-fable-5-1",
                "messages": [
                    ("user", "the delegated goal"),
                    ("assistant", "an answer the schema refused"),
                    ("user", "the schema retry"),
                ],
                "started_at": NOW - 60,
                "usage": {"model": "claude-fable-5-1", "output_tokens": 10, "last_seen": NOW - 5},
            }
        )
        self.assertEqual(attestation["verdict"], "unknown")
        self.assertEqual(attestation["basis"], "requested_model_prompt_may_be_rebuilt")

    def test_a_single_turn_child_with_its_goal_attests(self):
        # The negative control for the guard above: one user message, the
        # goal, and nothing archived is the shape whose stored prompt is the
        # first turn's build.
        attestation = self._attestation(
            {
                "id": "20260818_100100_oneturn",
                "model": "claude-fable-5-1",
                "prompt_model": "gpt-6-astra",
                "messages": [("user", "the delegated goal"), ("assistant", "done")],
                "started_at": NOW - 60,
                "usage": {"model": "claude-fable-5-1", "output_tokens": 10, "last_seen": NOW - 5},
            }
        )
        self.assertEqual(attestation["verdict"], "disagreement")
        self.assertEqual(attestation["requested"], "gpt-6-astra")
        self.assertEqual(attestation["requested_source"], "prompt_identity")

    def test_a_withheld_prompt_still_shows_a_session_row_disagreement(self):
        # Withholding the prompt withholds an agreement only; a session row
        # that differs from the sole answering model is still a substitution.
        attestation = self._attestation(
            {
                "id": "20260818_100100_wheldis",
                "model": "gpt-6-astra",
                "prompt_model": "claude-fable-5-1",
                "archived_messages": [("user", "the delegated goal")],
                "started_at": NOW - 60,
                "usage": {"model": "claude-fable-5-1", "output_tokens": 10, "last_seen": NOW - 5},
            }
        )
        self.assertEqual(attestation["verdict"], "disagreement")
        self.assertEqual(attestation["requested"], "gpt-6-astra")
        self.assertEqual(attestation["requested_source"], "session_model")

    def test_a_child_with_no_stored_prompt_is_not_attested_even_when_compacted(self):
        # No prompt is stored, so there is nothing Hermes could have rebuilt:
        # the basis is the missing request, whatever the archive holds.
        attestation = self._attestation(
            {
                "id": "20260818_100100_nullarc",
                "model": "claude-fable-5-1",
                "archived_messages": [("user", "the delegated goal")],
                "messages": [("assistant", "[compaction summary]")],
                "started_at": NOW - 60,
                "usage": {"model": "claude-fable-5-1", "output_tokens": 10, "last_seen": NOW - 5},
            }
        )
        self.assertEqual(attestation["verdict"], "unknown")
        self.assertEqual(attestation["basis"], "requested_model_not_attested")

    def test_a_schema_without_message_activity_attests_nothing(self):
        # Without `messages.active` an in-place compaction cannot be seen, so
        # no stored prompt is read as a request.
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260818_100100_noactiv",
                    "model": "claude-fable-5-1",
                    "prompt_model": "claude-fable-5-1",
                    "started_at": NOW - 60,
                    "usage": {
                        "model": "claude-fable-5-1",
                        "output_tokens": 10,
                        "last_seen": NOW - 5,
                    },
                }
            ],
            include_prompt_columns=True,
        )
        connection = sqlite3.connect(self.home / "state.db")
        connection.execute("ALTER TABLE messages DROP COLUMN active")
        connection.commit()
        connection.close()
        attestation = read_hermes_native_subagents(
            self.home, now=NOW, omh_home=self.home / ".omh"
        )["rows"][0]["model_attestation"]
        self.assertEqual(attestation["verdict"], "unknown")
        self.assertEqual(attestation["basis"], "requested_model_not_attested")

    def test_a_schema_that_cannot_tell_a_first_segment_attests_nothing(self):
        # Without `parent_session_id` a first segment and a continuation look
        # alike, so no stored prompt is read as a request.
        attestation = self._attestation(
            {
                "id": "20260818_100100_nocolum",
                "model": "claude-fable-5-1",
                "started_at": NOW - 60,
                "usage": {"model": "claude-fable-5-1", "output_tokens": 10, "last_seen": NOW - 5},
            },
            include_prompt_columns=False,
        )
        self.assertEqual(attestation["verdict"], "unknown")
        self.assertEqual(attestation["basis"], "requested_model_not_attested")

    def test_an_inline_legacy_prompt_attests_like_a_stored_one(self):
        attestation = self._attestation(
            {
                "id": "20260818_100100_inline1",
                "model": "claude-fable-5-1",
                "prompt_model": "gpt-6-astra",
                "prompt_inline": True,
                "started_at": NOW - 60,
                "usage": {"model": "claude-fable-5-1", "output_tokens": 10, "last_seen": NOW - 5},
            }
        )
        self.assertEqual(attestation["verdict"], "disagreement")
        self.assertEqual(attestation["requested"], "gpt-6-astra")
        self.assertEqual(attestation["requested_source"], "prompt_identity")

    def test_only_the_identity_trailer_names_the_request(self):
        # Memory and context files come before the trailer and may carry a
        # `Model:` line of their own; the runtime block after it is embedder
        # prose. Neither is read, only the trailer paragraph.
        prompt = _identity_prompt(
            "gpt-6-astra",
            # Memory may quote an earlier prompt's trailer and the runtime
            # heading verbatim. Only the LAST heading starts the runtime
            # block: cut at the first one, the quoted trailer would be read
            # as this child's request and attest an agreement.
            earlier=(
                "## Memory\nModel: claude-fable-5-1\n\n"
                "Conversation started: Monday, August 18, 2026\n"
                "Model: claude-fable-5-1\nProvider: openrouter\n\n"
                "# Hermes runtime environment\n\nquoted from a note"
            ),
            runtime="Model: claude-fable-5-1\nCurrent working directory: /tmp",
        )
        attestation = self._attestation(
            {
                "id": "20260818_100100_trailr1",
                "model": "claude-fable-5-1",
                "prompt": prompt,
                "started_at": NOW - 60,
                "usage": {"model": "claude-fable-5-1", "output_tokens": 10, "last_seen": NOW - 5},
            }
        )
        self.assertEqual(attestation["verdict"], "disagreement")
        self.assertEqual(attestation["requested"], "gpt-6-astra")

    def test_a_trailer_without_a_model_line_attests_nothing(self):
        # An earlier paragraph's `Model:` line never stands in for a trailer
        # that has none.
        prompt = _identity_prompt("", earlier="## Memory\nModel: claude-fable-5-1")
        attestation = self._attestation(
            {
                "id": "20260818_100100_nomodel",
                "model": "claude-fable-5-1",
                "prompt": prompt,
                "started_at": NOW - 60,
                "usage": {"model": "claude-fable-5-1", "output_tokens": 10, "last_seen": NOW - 5},
            }
        )
        self.assertEqual(attestation["verdict"], "unknown")
        self.assertEqual(attestation["basis"], "requested_model_not_attested")

    def test_the_trailer_reader_refuses_a_tail_it_cannot_bound(self):
        # The reader takes only the end of a stored prompt. A tail with no
        # paragraph break before the trailer, or a runtime block whose heading
        # is outside the tail, is not known to hold the whole trailer.
        self.assertEqual(_prompt_identity_model(_identity_prompt("gpt-6-astra")), "gpt-6-astra")
        self.assertEqual(_prompt_identity_model("Model: gpt-6-astra\nProvider: openrouter"), "")
        self.assertEqual(
            _prompt_identity_model(
                "Model: gpt-6-astra\n\nnot the heading\n\n<!-- End Hermes runtime environment -->"
            ),
            "",
        )
        self.assertEqual(
            _prompt_identity_model(
                _identity_prompt("gpt-6-astra", runtime="Model: claude-fable-5-1")
            ),
            "gpt-6-astra",
        )

    def test_the_trailer_reader_reads_only_a_paragraph_of_trailer_lines(self):
        # Every shape `_timestamp_line` writes is read...
        for trailer in (
            "Conversation started: Monday, August 18, 2026 (KST, UTC+09:00)\nModel: gpt-6-astra",
            "Conversation started: Monday, August 18, 2026\nToday's date (as of the last context "
            "rebuild): Tuesday, August 19, 2026 — trust this over the start date.\nModel: gpt-6-astra",
            "Timezone: KST, UTC+09:00\nSession ID: abc\nModel: gpt-6-astra\nProvider: openrouter",
            # an empty timestamp line leaves the labels after a blank line
            "\nModel: gpt-6-astra\nPlatform: cli",
        ):
            with self.subTest(trailer=trailer):
                prompt = "You are a helpful agent.\n\n## Memory\nModel: claude-fable-5-1\n\n" + trailer
                self.assertEqual(_prompt_identity_model(prompt), "gpt-6-astra")
        # ...and a last paragraph that is prose is not a trailer, even when a
        # line in it looks like one: that is a prompt with no trailer at all.
        for prose in (
            "## Memory\nModel: claude-fable-5-1",
            "Model: claude-fable-5-1\nremember to be brief",
        ):
            with self.subTest(prose=prose):
                self.assertEqual(_prompt_identity_model("You are a helpful agent.\n\n" + prose), "")

    def test_a_child_that_changed_models_mid_run_attests_unknown_not_agreement(self):
        # `_sole_distinct_value` hands two distinct usage models over as an
        # empty string, which is the right answer for the `model` column and
        # a trap for a verdict: an empty answering side must never read as a
        # match against the request.
        attestation = self._attestation(
            {
                "id": "20260818_100100_switch",
                "model": "claude-fable-5-1",
                "prompt_model": "claude-fable-5-1",
                "started_at": NOW - 60,
                "usages": [
                    {"model": "claude-fable-5-1", "output_tokens": 10, "last_seen": NOW - 20},
                    {"model": "gpt-6-astra", "output_tokens": 10, "last_seen": NOW - 5},
                ],
            }
        )
        self.assertEqual(attestation["verdict"], "unknown")
        self.assertEqual(attestation["basis"], "multiple_usage_models")
        self.assertNotIn("answering", attestation)
        self.assertEqual(attestation["requested"], "claude-fable-5-1")

    def test_a_child_with_no_usage_row_attests_unknown(self):
        attestation = self._attestation(
            {
                "id": "20260818_100100_nousage",
                "model": "claude-fable-5-1",
                "started_at": NOW - 60,
            }
        )
        self.assertEqual(attestation["verdict"], "unknown")
        self.assertEqual(attestation["basis"], "no_usage_observation")
        self.assertNotIn("answering", attestation)
        # An unattested session row is not named the request either.
        self.assertNotIn("requested", attestation)

    def test_an_auxiliary_call_on_another_model_leaves_the_answer_standing(self):
        # Hermes records a compression call under its task name on the aux
        # route's model. It is spend, so the tokens keep it, but it did not
        # answer the child.
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260818_100100_auxrow1",
                    "model": "claude-fable-5-1",
                    "prompt_model": "claude-fable-5-1",
                    "started_at": NOW - 60,
                    "usages": [
                        {"model": "claude-fable-5-1", "output_tokens": 10, "last_seen": NOW - 5},
                        {
                            "model": "gemini-3-flash",
                            "task": "compression",
                            "output_tokens": 3,
                            "last_seen": NOW - 4,
                        },
                    ],
                }
            ],
            include_prompt_columns=True,
            include_usage_task=True,
        )
        row = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home / ".omh")["rows"][0]
        self.assertEqual(row["model_attestation"]["verdict"], "agreement")
        self.assertEqual(row["model_attestation"]["answering"], "claude-fable-5-1")
        self.assertEqual(row["tokens"], 13)

    def test_a_child_whose_only_call_is_auxiliary_has_no_answering_model(self):
        # Read as the answer, the vision call's model disagreed with the
        # attested request: a false alarm about a call the child never made.
        attestation = self._attestation(
            {
                "id": "20260818_100100_auxonly",
                "model": "claude-fable-5-1",
                "prompt_model": "claude-fable-5-1",
                "started_at": NOW - 60,
                "usage": {
                    "model": "gemini-3-flash",
                    "task": "vision",
                    "output_tokens": 3,
                    "last_seen": NOW - 4,
                },
            },
            include_usage_task=True,
        )
        self.assertEqual(attestation["verdict"], "unknown")
        self.assertEqual(attestation["basis"], "no_usage_observation")
        self.assertNotIn("answering", attestation)

    def test_an_auxiliary_only_child_is_priced_at_the_model_its_calls_ran_on(self):
        # No answering model names the row, but the tokens are real spend:
        # the approximation prices them at the one model they ran on, at the
        # operator's own rate for it when there is one.
        price_path = self.home / ".omh" / "routing" / "model-prices.json"
        price_path.parent.mkdir(parents=True)
        price_path.write_text(
            json.dumps(
                {
                    "schema_version": "model_price_overrides/v1",
                    "models": {"deepseek-v4.1-flash": {"input_per_mtok": 1.0, "output_per_mtok": 2.0}},
                }
            ),
            encoding="utf-8",
        )
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260818_100100_auxcost",
                    "model": "",
                    "started_at": NOW - 60,
                    "usage": {
                        "model": "deepseek-v4.1-flash",
                        "task": "compression",
                        "input_tokens": 500,
                        "output_tokens": 50,
                        "last_seen": NOW - 4,
                    },
                }
            ],
            include_usage_task=True,
        )
        row = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home / ".omh")["rows"][0]
        self.assertEqual(row["model"], "")
        self.assertEqual((row["alias"], row["category"]), ("", ""))
        self.assertEqual(row["model_attestation"]["basis"], "no_usage_observation")
        self.assertTrue(row["cost_approximate"])
        self.assertTrue(row["cost_override"])
        self.assertAlmostEqual(row["cost_usd"], (500 * 1.0 + 50 * 2.0) / 1_000_000)

    def test_an_empty_session_model_prices_like_the_answering_model_it_names(self):
        # Hermes leaves `sessions.model` empty on some children. Once the
        # answering model fills it, the row prices like one whose session row
        # named that model: every token, auxiliary calls included.
        usages = [
            {"model": "claude-opus-5-5", "input_tokens": 1000, "output_tokens": 200, "last_seen": NOW - 20},
            {
                "model": "deepseek-v4.1-flash",
                "task": "compression",
                "input_tokens": 500,
                "output_tokens": 50,
                "last_seen": NOW - 10,
            },
        ]
        _build_state_db(
            self.home,
            [
                {"id": "20260818_100100_emptym1", "model": "", "started_at": NOW - 60, "usages": usages},
                {"id": "20260818_100100_namedm1", "model": "claude-opus-5-5", "started_at": NOW - 60, "usages": usages},
            ],
            include_usage_task=True,
        )
        rows = {
            row["task_id"]: row
            for row in read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home / ".omh")["rows"]
        }
        empty, named = rows["emptym1"], rows["namedm1"]
        self.assertEqual(empty["model"], "claude-opus-5-5")
        self.assertEqual((empty["tokens"], empty["category"]), (named["tokens"], named["category"]))
        self.assertTrue(empty["cost_approximate"])
        self.assertAlmostEqual(empty["cost_usd"], named["cost_usd"])
        self.assertAlmostEqual(
            empty["cost_usd"],
            hermes_delegation_module._approximate_cost_usd("claude-opus-5-5", 1500, 250, 0),
        )

    def test_a_switch_between_the_childs_own_calls_still_reads_as_a_switch(self):
        # The task filter drops auxiliary rows only: two models on the
        # child's own turns are still a mid-run switch.
        attestation = self._attestation(
            {
                "id": "20260818_100100_ownswch",
                "model": "claude-fable-5-1",
                "prompt_model": "claude-fable-5-1",
                "started_at": NOW - 60,
                "usages": [
                    {"model": "claude-fable-5-1", "output_tokens": 10, "last_seen": NOW - 20},
                    {"model": "gpt-6-astra", "output_tokens": 10, "last_seen": NOW - 5},
                ],
            },
            include_usage_task=True,
        )
        self.assertEqual(attestation["verdict"], "unknown")
        self.assertEqual(attestation["basis"], "multiple_usage_models")

    def test_a_usage_table_without_a_task_column_reads_every_row_as_before(self):
        # A state.db from before Hermes split auxiliary calls out has no way
        # to tell one, so every row still counts toward the answer.
        attestation = self._attestation(
            {
                "id": "20260818_100100_notask1",
                "model": "claude-fable-5-1",
                "prompt_model": "claude-fable-5-1",
                "started_at": NOW - 60,
                "usages": [
                    {"model": "claude-fable-5-1", "output_tokens": 10, "last_seen": NOW - 5},
                    {"model": "gemini-3-flash", "output_tokens": 3, "last_seen": NOW - 4},
                ],
            }
        )
        self.assertEqual(attestation["verdict"], "unknown")
        self.assertEqual(attestation["basis"], "multiple_usage_models")

    def test_a_vendor_pointer_answered_by_its_exact_contract_id_agrees(self):
        # `deepseek-flash` is DeepSeek's served pointer for the exact contract
        # id a gateway reports. Two spellings, one model: a disagreement here
        # would be a false alarm on every gateway route.
        attestation = self._attestation(
            {
                "id": "20260818_100100_pointer",
                "model": "deepseek-flash",
                "prompt_model": "deepseek-flash",
                "started_at": NOW - 60,
                "usage": {
                    "model": "deepseek/deepseek-v4.1-flash",
                    "output_tokens": 10,
                    "last_seen": NOW - 5,
                },
            }
        )
        self.assertEqual(attestation["verdict"], "agreement")
        self.assertEqual(attestation["requested"], "deepseek-v4.1-flash")
        self.assertEqual(attestation["answering"], "deepseek-v4.1-flash")

    def test_a_dated_snapshot_of_the_requested_model_agrees(self):
        # `<base>-YYYY-MM-DD` is the base pinned to a release date, so a
        # snapshot answering the base is the same model, not a substitution.
        attestation = self._attestation(
            {
                "id": "20260818_100100_snapsho",
                "model": "gpt-6-astra",
                "prompt_model": "gpt-6-astra",
                "started_at": NOW - 60,
                "usage": {
                    "model": "gpt-6-astra-2026-07-09",
                    "output_tokens": 10,
                    "last_seen": NOW - 5,
                },
            }
        )
        self.assertEqual(attestation["verdict"], "agreement")
        self.assertEqual(attestation["requested"], "gpt-6-astra")
        self.assertEqual(attestation["answering"], "gpt-6-astra")

    def test_a_new_pointer_alias_moves_the_verdict_through_the_shared_table(self):
        # The no-second-copy proof: the comparison resolves through
        # `_model_alias_candidates`, the same list the category label matches
        # chains against. Declaring one more pointer row is the whole change
        # a future model generation needs.
        from unittest import mock

        child = {
            "id": "20260818_100100_newptr1",
            "model": "claude-fable-5-1",
            "prompt_model": "claude-fable-5-1",
            "started_at": NOW - 60,
            "usage": {
                "model": "anthropic/claude-fable-5-1-preview",
                "output_tokens": 10,
                "last_seen": NOW - 5,
            },
        }
        self.assertEqual(self._attestation(child)["verdict"], "disagreement")
        with mock.patch.object(
            hermes_delegation_module,
            "EXACT_CONTRACT_POINTER_ALIASES",
            {"claude-fable-5-1-preview": ("claude-fable-5-1",)},
        ):
            attestation = read_hermes_native_subagents(
                self.home, now=NOW, omh_home=self.home / ".omh"
            )["rows"][0]["model_attestation"]
        self.assertEqual(attestation["verdict"], "agreement")
        self.assertEqual(attestation["requested"], "claude-fable-5-1")
        self.assertEqual(attestation["answering"], "claude-fable-5-1-preview")
        # The requested side already spells the shared identity, so no third
        # name is added; `resolved` appears only when neither side names it.
        self.assertNotIn("resolved", attestation)

    def test_a_shared_identity_neither_side_spells_is_named_on_its_own(self):
        # Two speed tiers of one model: the sides agree on `glm-5.3`, and
        # neither the requested nor the answering spelling says so.
        attestation = self._attestation(
            {
                "id": "20260818_100100_tiers11",
                "model": "glm-5.3-ultrafast",
                "prompt_model": "glm-5.3-ultrafast",
                "started_at": NOW - 60,
                "usage": {"model": "glm-5.3-fast", "output_tokens": 10, "last_seen": NOW - 5},
            }
        )
        self.assertEqual(attestation["verdict"], "agreement")
        self.assertEqual(attestation["requested"], "glm-5.3-ultrafast")
        self.assertEqual(attestation["answering"], "glm-5.3-fast")
        self.assertEqual(attestation["resolved"], "glm-5.3")

    def _write_delegation_model(self, model: str) -> None:
        (self.home / "config.yaml").write_text(
            f"delegation:\n  model: '{model}'\n", encoding="utf-8"
        )

    def _read_attestation(self) -> dict:
        return read_hermes_native_subagents(
            self.home, now=NOW, omh_home=self.home / ".omh"
        )["rows"][0]["model_attestation"]

    def test_a_child_with_no_recorded_model_is_unknown_whatever_the_config_says(self):
        # `sessions.model` can be empty on a child, and then nothing from the
        # run records what was asked for. Today's `delegation.model` is not
        # that record: OMH rewrites it per dispatch and restores it at turn
        # end. A config that would agree with the answering model and one
        # that would not must both leave the verdict unknown.
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260818_100100_routed1",
                    "model": "",
                    "started_at": NOW - 600,
                    "usage": {
                        "model": "claude-fable-5-1",
                        "output_tokens": 10,
                        "last_seen": NOW - 300,
                    },
                }
            ],
        )
        for configured in ("claude-fable-5-1", "gpt-6-astra"):
            with self.subTest(delegation_model=configured):
                self._write_delegation_model(configured)
                attestation = self._read_attestation()
                self.assertEqual(attestation["verdict"], "unknown")
                self.assertEqual(attestation["basis"], "no_requested_model")
                self.assertEqual(attestation["answering"], "claude-fable-5-1")
                self.assertNotIn("requested", attestation)
                self.assertNotIn("requested_source", attestation)

    def test_a_finished_childs_verdict_does_not_move_when_the_config_does(self):
        # The defect itself: one finished child, read twice, with only
        # `delegation.model` rewritten between the reads. The verdict
        # belongs to the run, so the two reads must be identical.
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260818_100100_pastrun",
                    "model": "",
                    "started_at": NOW - 600,
                    "usage": {
                        "model": "claude-fable-5-1",
                        "output_tokens": 10,
                        "last_seen": NOW - 300,
                    },
                }
            ],
        )
        payload = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home / ".omh")
        self.assertEqual(payload["rows"][0]["state"], "done")
        self._write_delegation_model("claude-fable-5-1")
        before = self._read_attestation()
        self._write_delegation_model("gpt-6-astra")
        after = self._read_attestation()
        self.assertEqual(before, after)

    def test_a_recorded_request_keeps_its_verdict_against_a_contradicting_config(self):
        # The negative control: a child is judged on its own records alone,
        # so a config saying the opposite moves neither an attested agreement
        # nor a session-row disagreement.
        cases = (
            ("20260818_100100_keepagr", "claude-fable-5-1", "claude-fable-5-1",
             "gpt-6-astra", "agreement", "prompt_identity"),
            ("20260818_100100_keepdis", "gpt-6-astra", None,
             "claude-fable-5-1", "disagreement", "session_model"),
        )
        for child_id, recorded, prompt_model, configured, verdict, source in cases:
            with self.subTest(recorded=recorded, configured=configured):
                (self.home / "state.db").unlink(missing_ok=True)
                child = {
                    "id": child_id,
                    "model": recorded,
                    "started_at": NOW - 60,
                    "usage": {
                        "model": "claude-fable-5-1",
                        "output_tokens": 10,
                        "last_seen": NOW - 5,
                    },
                }
                if prompt_model:
                    child["prompt_model"] = prompt_model
                _build_state_db(self.home, [child], include_prompt_columns=True)
                self._write_delegation_model(configured)
                attestation = self._read_attestation()
                self.assertEqual(attestation["verdict"], verdict)
                self.assertEqual(attestation["requested"], recorded)
                self.assertEqual(attestation["requested_source"], source)

    def test_a_child_nothing_recorded_a_request_for_attests_unknown(self):
        # No session model and no config at all: the answering model is
        # observed, and there is nothing to attest it against.
        attestation = self._attestation(
            {
                "id": "20260818_100100_noreq11",
                "model": "",
                "started_at": NOW - 60,
                "usage": {"model": "claude-fable-5-1", "output_tokens": 10, "last_seen": NOW - 5},
            }
        )
        self.assertEqual(attestation["verdict"], "unknown")
        self.assertEqual(attestation["basis"], "no_requested_model")
        self.assertEqual(attestation["answering"], "claude-fable-5-1")
        self.assertNotIn("requested_source", attestation)

    def test_the_payload_states_what_the_verdict_covers(self):
        # The coverage limit is in the output, not left to the reader: every
        # row carries the scope token, and the payload carries the sentence.
        _build_state_db(
            self.home,
            [
                {
                    "id": "20260818_100100_cover11",
                    "model": "claude-fable-5-1",
                    "prompt_model": "claude-fable-5-1",
                    "started_at": NOW - 60,
                    "usage": {
                        "model": "claude-fable-5-1",
                        "output_tokens": 10,
                        "last_seen": NOW - 5,
                    },
                }
            ],
            include_prompt_columns=True,
        )
        payload = read_hermes_native_subagents(self.home, now=NOW, omh_home=self.home / ".omh")
        self.assertEqual(
            payload["rows"][0]["model_attestation"]["coverage"], "delegation_child"
        )
        self.assertEqual(payload["attestation_coverage"], ATTESTATION_COVERAGE_CLAIM)
        self.assertIn("delegation children only", payload["attestation_coverage"])
        self.assertIn("main session", payload["attestation_coverage"])

    def test_the_comparison_separates_the_two_reasons_it_cannot_resolve(self):
        # The function's own contract, independent of the reader: the
        # distinct-model count is what separates "nothing observed" from "more
        # than one model answered", and neither is agreement.
        self.assertEqual(
            served_model_attestation("gpt-6-astra", "", answering_observations=0)["basis"],
            "no_usage_observation",
        )
        self.assertEqual(
            served_model_attestation("gpt-6-astra", "", answering_observations=2)["basis"],
            "multiple_usage_models",
        )
        for observations in (0, 2):
            self.assertEqual(
                served_model_attestation(
                    "gpt-6-astra", "", answering_observations=observations
                )["verdict"],
                "unknown",
            )

    def test_a_caller_that_does_not_attest_its_request_gets_no_agreement(self):
        # The default is the fail-safe one: agreement needs a caller that says
        # its request is attested.
        unattested = served_model_attestation("gpt-6-astra", "gpt-6-astra")
        self.assertEqual(unattested["verdict"], "unknown")
        self.assertEqual(unattested["basis"], "requested_model_not_attested")
        attested = served_model_attestation(
            "gpt-6-astra", "gpt-6-astra", request_attested=True
        )
        self.assertEqual(attested["verdict"], "agreement")
        self.assertEqual(
            served_model_attestation("gpt-6-astra", "claude-fable-5-1")["verdict"],
            "disagreement",
        )


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
                            "kimi-k3.1-pro": {
                                "provider": "gateway",
                                "model": "moonshotai/kimi-k3.1-pro",
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
                        "model": "moonshotai/kimi-k3.1-pro",
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

            self.assertEqual(row["alias"], "kimi-k3.1-pro")
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
                        "model": "gpt-6.1-sol",
                        "prompt_model": "gpt-6.1-sol",
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
                include_prompt_columns=True,
            )
            payload = read_omh_hud(omh_home, hermes_home)
            self.assertTrue(payload["active"])
            self.assertEqual(payload["subagents"]["running"], 1)
            rows = payload["subagents"]["rows"]
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["role"], "hermes-native")
            # gpt-6.1-sol:high sits second in the deep chain (behind Opus 5.5
            # since 2026-10-13), heads no chain, and differs from the parent
            # model, so the projected category is visible in the HUD row.
            self.assertEqual(rows[0]["category"], "deep")
            # Nothing was dropped, so the disclosed hidden-row count is zero.
            self.assertEqual(payload["subagents"]["hidden_rows"], 0)
            # The served-model verdict rides along with its coverage limit:
            # the native rows are the only ones that carry a verdict, so the
            # sentence describing what it covers travels with them.
            self.assertEqual(rows[0]["model_attestation"]["verdict"], "agreement")
            self.assertEqual(
                payload["subagents"]["attestation_coverage"], ATTESTATION_COVERAGE_CLAIM
            )

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
        "alias": "kimi-k3.1-pro",
        "wire_model": "moonshotai/kimi-k3.1-pro",
        "provider": "gateway",
        "reasoning_effort": "low",
        "from_alias": "claude-fable-5-1",
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

    def test_the_preparing_session_round_trips_when_the_writer_names_one(self):
        append_delegation_route_provenance(_record(session_id=PARENT_ID), self.home)
        self.assertEqual(
            load_delegation_route_provenance(self.home)[-1]["session_id"], PARENT_ID
        )

    def test_a_writer_that_names_no_session_writes_the_pre_field_record(self):
        # Additive-optional: an empty owner and an absent one both produce
        # the record shape this store had before the field existed, so a
        # caller that cannot name its session writes the same bytes it did.
        for record in (_record(), _record(session_id="")):
            with self.subTest(keys=sorted(record)):
                (self.home / "routing" / "route-provenance.json").unlink(missing_ok=True)
                append_delegation_route_provenance(record, self.home)
                written = load_delegation_route_provenance(self.home)[-1]
                self.assertEqual(
                    sorted(written),
                    [
                        "alias",
                        "category",
                        "from_alias",
                        "origin",
                        "provider",
                        "reasoning_effort",
                        "wire_model",
                        "written_at",
                    ],
                )

    def test_a_malformed_owner_reads_as_no_provenance_and_never_raises(self):
        for owner in (17, None, ["a"], {"id": "a"}, True, "x" * 161):
            with self.subTest(owner=owner):
                self.assertEqual(
                    append_delegation_route_provenance(_record(session_id=owner), self.home),
                    "unrecorded: invalid record",
                )
                _write_provenance(self.home, [_record(session_id=owner)])
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
                        "kimi-k3.1-pro": {
                            "provider": "gateway",
                            "model": "moonshotai/kimi-k3.1-pro",
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
        row = self._row("moonshotai/kimi-k3.1-pro")
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
        row = self._row("moonshotai/kimi-k3.1-pro")
        self.assertNotIn("route_origin", row)
        self.assertNotIn("category_source", row)
        self.assertEqual(row["category"], "quick")

    def test_a_route_to_the_parents_own_model_keeps_its_category_and_says_so(self):
        # The parent's own model can also be a chain head (the owner's
        # `deep` heads on the model the session runs). A fresh record whose
        # identity matches proves the tool routed the lane there; the row
        # keeps the lane's category and says the model is the parent's own,
        # so the label is neither "unrouted" nor "a cheaper dispatch".
        _write_provenance(
            self.home,
            [_record(origin="head", alias="gpt-5.6-sol", wire_model="gpt-5.6-sol", provider="")],
        )
        row = self._row("gpt-5.6-sol")
        self.assertEqual(row["category"], "visual-engineering")
        self.assertEqual(row["category_source"], "route_provenance")
        self.assertIs(row["same_as_parent"], True)
        self.assertNotIn("route_origin", row)

    def test_a_fallback_to_the_parents_own_model_keeps_both_tokens(self):
        _write_provenance(
            self.home,
            [_record(origin="fallback", alias="gpt-5.6-sol", wire_model="gpt-5.6-sol", provider="")],
        )
        row = self._row("gpt-5.6-sol")
        self.assertEqual(row["category"], "visual-engineering")
        self.assertEqual(row["route_origin"], "fallback")
        self.assertIs(row["same_as_parent"], True)

    def test_an_unrouted_child_on_the_parents_model_stays_plain_inherit(self):
        # No record, a stale record, or a cleared route: the chain
        # projection's inherit stands and nothing claims a category.
        for records in (
            [],
            [_record(alias="gpt-5.6-sol", wire_model="gpt-5.6-sol", provider="", written_at=NOW - 2000)],
            [_record(alias="gpt-5.6-sol", wire_model="gpt-5.6-sol", provider=""), {"origin": "cleared", "written_at": NOW - 100}],
        ):
            with self.subTest(records=records):
                _write_provenance(self.home, records)
                (self.home / "state.db").unlink(missing_ok=True)
                row = self._row("gpt-5.6-sol")
                self.assertEqual(row["category"], "inherit")
                self.assertNotIn("same_as_parent", row)
                self.assertNotIn("category_source", row)

    def test_a_routed_child_on_another_model_never_carries_the_parent_token(self):
        _write_provenance(self.home, [_record(origin="head")])
        row = self._row("moonshotai/kimi-k3.1-pro")
        self.assertEqual(row["category"], "visual-engineering")
        self.assertNotIn("same_as_parent", row)

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
        row = self._row("moonshotai/kimi-k3.1-pro")
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
                row = self._row("moonshotai/kimi-k3.1-pro")
                self.assertNotIn("route_origin", row)
                self.assertEqual(row["category"], "quick")
