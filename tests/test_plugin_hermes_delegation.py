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

from omh.plugin_bundle.omh.hermes_delegation import (
    COMPLETED_LINGER_SECONDS,
    HERMES_MIXTURE_CATEGORY_CHAINS,
    MIXTURE_CHAIN_OVERRIDES_SCHEMA_VERSION,
    RECENT_ACTIVITY_SECONDS,
    effective_mixture_category_chains,
    load_mixture_chain_overrides,
    mixture_category_for,
    mixture_chain_overrides_path,
    parse_model_provider_routes,
    read_hermes_native_subagents,
)

NOW = 1_800_000_000.0
PARENT_ID = "20260818_100000_parent"


def _build_state_db(
    home: Path,
    children: list[dict],
    *,
    delegation_states: dict[str, str] | None = None,
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
            first_seen REAL, last_seen REAL
        );
        CREATE TABLE async_delegations (
            delegation_id TEXT PRIMARY KEY, state TEXT NOT NULL,
            dispatched_at REAL NOT NULL
        );
        """
    )
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
        usage = child.get("usage")
        if usage:
            connection.execute(
                "INSERT INTO session_model_usage VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    child["id"],
                    child["model"],
                    usage.get("api_calls", 0),
                    usage.get("input_tokens", 0),
                    usage.get("output_tokens", 0),
                    usage.get("cache_read_tokens", 0),
                    usage.get("actual_cost_usd", 0.0),
                    usage.get("estimated_cost_usd", 0.0),
                    usage.get("first_seen"),
                    usage.get("last_seen"),
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
        # glm-5.2-ultrafast:low heads `quick` and is also second in
        # unspecified-low; the head attribution wins.
        self.assertEqual(
            mixture_category_for("glm-5.2-ultrafast", "low", parent_model="kimi-k3"),
            "quick",
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


def _write_overrides(omh_home: Path, document: object) -> Path:
    path = mixture_chain_overrides_path(omh_home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


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


if __name__ == "__main__":
    unittest.main()
