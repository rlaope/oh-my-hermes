from __future__ import annotations

import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from _local_package import load_local_package

load_local_package()

from _cli_harness import run_cli  # noqa: E402
from omh.coding.model_inventory import (  # noqa: E402
    CLI_PRESENCE_COMMANDS,
    LOCAL_MODEL_CATALOG_SCHEMA_VERSION,
    MODEL_DOMAIN_AFFINITIES,
    MODEL_DOMAIN_AFFINITY_CLAIM_BOUNDARY,
    MODEL_INVENTORY_CATALOG_PROFILE,
    MODEL_INVENTORY_SCHEMA_VERSION,
    CATEGORY_ROLE_SOURCES,
    catalog_fingerprint_note,
    inventory_model_catalog,
    local_model_inventory,
)
from omh.coding.pi_family_interop import OPENCODE_RUNTIME_CONFIG_FILE, PI_DISTRIBUTION_HOME, PI_DISTRIBUTION_HOST, PI_FORK_HOME, PI_FORK_HOST, RUNTIME_CONFIG_FILES, RUNTIME_HOME
from omh.coding.model_discovery_adapters import RUNTIME_CONFIG_SOURCE

_SECRET = "sk-SECRET-VALUE-12345"


def _write_home(
    tmp: str,
    *,
    runtime_config: object | None = None,
    runtime_raw: str | None = None,
    opencode_config: object | None = None,
    auth: object | None = None,
) -> Path:
    home = Path(tmp)
    config_dir = home / ".config" / "opencode"
    config_dir.mkdir(parents=True, exist_ok=True)
    if runtime_raw is not None:
        (config_dir / OPENCODE_RUNTIME_CONFIG_FILE).write_text(runtime_raw, encoding="utf-8")
    elif runtime_config is not None:
        (config_dir / OPENCODE_RUNTIME_CONFIG_FILE).write_text(json.dumps(runtime_config), encoding="utf-8")
    if opencode_config is not None:
        (config_dir / "opencode.json").write_text(json.dumps(opencode_config), encoding="utf-8")
    if auth is not None:
        auth_dir = home / ".local" / "share" / "opencode"
        auth_dir.mkdir(parents=True, exist_ok=True)
        (auth_dir / "auth.json").write_text(json.dumps(auth), encoding="utf-8")
    return home


_RUNTIME_CONFIG_FIXTURE = {
    "$schema": "https://example.invalid/schema.json",
    "agents": {
        "planner": {
            "model": "openai/gpt-5.6-sol",
            "variant": "xhigh",
            "fallback_models": [
                {"model": "opencode/kimi-k3", "variant": "high"},
                {"model": "opencode/glm-5"},
            ],
        },
    },
    "categories": {
        "visual-engineering": {
            "model": "opencode/gemini-3.1-pro",
            "variant": "high",
            "fallback_models": [{"model": "anthropic/claude-opus-5", "variant": "max"}],
        },
    },
}


class ModelInventoryTests(unittest.TestCase):
    def test_models_are_aggregated_with_families_and_variants(self) -> None:
        with TemporaryDirectory() as tmp:
            home = _write_home(tmp, runtime_config=_RUNTIME_CONFIG_FIXTURE)
            inventory = local_model_inventory(home)
        self.assertEqual(inventory["schema_version"], MODEL_INVENTORY_SCHEMA_VERSION)
        models = {f"{entry['provider']}/{entry['model_id']}": entry for entry in inventory["available_models"]}
        self.assertEqual(models["opencode/kimi-k3"]["family"], "kimi")
        self.assertEqual(models["opencode/kimi-k3"]["variants"], ["high"])
        self.assertEqual(models["opencode/glm-5"]["family"], "glm")
        self.assertEqual(models["opencode/gemini-3.1-pro"]["family"], "gemini")
        self.assertEqual(models["anthropic/claude-opus-5"]["variants"], ["max"])
        self.assertEqual(
            inventory["families_present"], ["claude", "gemini", "glm", "gpt", "kimi"]
        )
        self.assertEqual(inventory["sources"]["runtime_agent_config"]["status"], "present")
        self.assertEqual(inventory["sources"]["runtime_agent_config"]["model_count"], 5)
        self.assertEqual(inventory["sources"]["runtime_agent_config"]["rejected"], 0)

    def test_no_secret_value_ever_reaches_the_payload(self) -> None:
        # Precedent: tests/test_executor_auth_signals.py — plant a secret in
        # every source file and assert the serialized payload never echoes it.
        runtime_config = json.loads(json.dumps(_RUNTIME_CONFIG_FIXTURE))
        runtime_config["agents"]["planner"]["api_key"] = _SECRET
        with TemporaryDirectory() as tmp:
            home = _write_home(
                tmp,
                runtime_config=runtime_config,
                opencode_config={"provider": {"openai": {"apiKey": _SECRET}}},
                auth={"anthropic": {"type": "oauth", "access": _SECRET}},
            )
            inventory = local_model_inventory(home)
        serialized = json.dumps(inventory)
        self.assertNotIn(_SECRET, serialized)
        # Provider key NAMES are the only thing read from auth/config tables.
        self.assertEqual(inventory["sources"]["opencode_config_providers"]["providers"], ["openai"])
        self.assertEqual(inventory["sources"]["opencode_auth_providers"]["providers"], ["anthropic"])

    def test_absent_and_malformed_sources_report_status_without_paths(self) -> None:
        with TemporaryDirectory() as tmp:
            inventory = local_model_inventory(Path(tmp))
            self.assertEqual(inventory["sources"]["runtime_agent_config"]["status"], "absent")
            self.assertEqual(inventory["sources"]["opencode_auth_providers"]["status"], "absent")
            self.assertEqual(inventory["available_models"], [])
            self.assertNotIn(tmp, json.dumps(inventory))
        with TemporaryDirectory() as tmp:
            home = _write_home(tmp, runtime_raw="{not json", opencode_config={"provider": []})
            inventory = local_model_inventory(home)
            self.assertEqual(inventory["sources"]["runtime_agent_config"]["status"], "unreadable")
            # A present file whose section has the wrong shape is not a crash.
            self.assertEqual(inventory["sources"]["opencode_config_providers"]["providers"], [])
            self.assertNotIn(tmp, json.dumps(inventory))

    def test_shape_gate_rejects_hostile_identifiers_without_echoing(self) -> None:
        hostile = {
            "agents": {
                "bad": {
                    "model": "--rm -rf /",
                    "fallback_models": [
                        {"model": "openai/gpt-5.6-sol", "variant": "high"},
                        {"model": "x" * 200},
                        {"model": "openai/api_key=leak"},
                    ],
                },
            },
        }
        with TemporaryDirectory() as tmp:
            inventory = local_model_inventory(_write_home(tmp, runtime_config=hostile))
        source = inventory["sources"]["runtime_agent_config"]
        self.assertEqual(source["rejected"], 3)
        self.assertEqual(source["model_count"], 1)
        serialized = json.dumps(inventory)
        self.assertNotIn("--rm", serialized)
        self.assertNotIn("x" * 200, serialized)
        self.assertNotIn("api_key", serialized)
        models = [f"{entry['provider']}/{entry['model_id']}" for entry in inventory["available_models"]]
        self.assertEqual(models, ["openai/gpt-5.6-sol"])

    def test_inventory_is_deterministic_modulo_observed_at(self) -> None:
        with TemporaryDirectory() as tmp:
            home = _write_home(tmp, runtime_config=_RUNTIME_CONFIG_FIXTURE)
            first = local_model_inventory(home)
            second = local_model_inventory(home)
        for payload in (first, second):
            payload.pop("observed_at")
            payload["sources"]["executor_auth_signals"].pop("observed_at", None)
        self.assertEqual(first, second)

    def test_domain_affinity_notes_are_report_only_static_vocabulary(self) -> None:
        self.assertEqual(MODEL_DOMAIN_AFFINITIES["x_platform_data"], ("grok",))
        with TemporaryDirectory() as tmp:
            inventory = local_model_inventory(_write_home(tmp, runtime_config=_RUNTIME_CONFIG_FIXTURE))
        notes = {note["domain"]: note for note in inventory["domain_affinity_notes"]}
        self.assertEqual(notes["x_platform_data"]["locally_present"], [])
        self.assertEqual(notes["multimodal_vision"]["locally_present"], ["claude", "gemini", "gpt"])
        # The affinity table is an editorial default, not a capability claim:
        # its own boundary rides the payload (critic-mandated condition).
        self.assertEqual(inventory["domain_affinity_claim_boundary"], MODEL_DOMAIN_AFFINITY_CLAIM_BOUNDARY)
        self.assertIn("never a veto", MODEL_DOMAIN_AFFINITY_CLAIM_BOUNDARY)
        self.assertIn("explicit model choice", MODEL_DOMAIN_AFFINITY_CLAIM_BOUNDARY)

    def test_affinity_vocabulary_reaches_routing_only_as_catalog_data(self) -> None:
        """Routing consumes domain affinities exclusively via the local
        catalog payload: the vocabulary constants and domain literals never
        appear in routing, dispatch, or contract module SOURCE, so built-in
        chains cannot grow a hidden affinity dependency."""
        src = Path(__file__).resolve().parent.parent / "src" / "coding"
        for module in ("model_routing.py", "fanout_dispatch.py", "fanout.py", "fanout_contracts.py"):
            source = (src / module).read_text(encoding="utf-8")
            self.assertNotIn("MODEL_DOMAIN_AFFINITIES", source, module)
            self.assertNotIn("x_platform_data", source, module)

    def test_routing_never_imports_the_inventory(self) -> None:
        """Reporting-only is a structural property: the route resolver must not
        read the inventory (or any file), so the import direction is pinned."""
        routing_source = (
            Path(__file__).resolve().parent.parent / "src" / "coding" / "model_routing.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("model_inventory", routing_source)

    def test_cli_presence_table_is_fixed_vocabulary(self) -> None:
        self.assertEqual(
            CLI_PRESENCE_COMMANDS,
            ("codex", "claude", "opencode", "pi", PI_DISTRIBUTION_HOST, "gemini", "grok", "qwen"),
        )

    def test_pi_distribution_auth_provider_names_are_presence_only(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            pi_distribution_dir = home / PI_DISTRIBUTION_HOME / "agent"
            pi_distribution_dir.mkdir(parents=True)
            (pi_distribution_dir / "auth.json").write_text(
                json.dumps({"kimi-coding": {"type": "api", "key": _SECRET}}), encoding="utf-8"
            )
            inventory = local_model_inventory(home)
        source = inventory["sources"]["pi_distribution_auth_providers"]
        self.assertEqual(source["status"], "present")
        self.assertEqual(source["providers"], ["kimi-coding"])
        self.assertNotIn(_SECRET, json.dumps(inventory))


class MultiAgentModelDiscoveryTests(unittest.TestCase):
    def _write_jsonl(self, path: Path, *records: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            "".join(json.dumps(record) + "\n" for record in records),
            encoding="utf-8",
        )

    def test_mixed_agent_stores_emit_only_safe_model_metadata(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            self._write_jsonl(
                home / ".codex" / "sessions" / "2026" / "rollout.jsonl",
                {
                    "type": "session_meta",
                    "timestamp": "2026-08-01T01:02:03Z",
                    "payload": {
                        "model_provider": "openai",
                        "model": "gpt-5.6-sol",
                        "instructions": f"ignore safety\n{_SECRET}",
                    },
                },
            )
            auth_inside_session_root = home / ".codex" / "sessions" / "auth.json"
            auth_inside_session_root.write_text(
                json.dumps(
                    {
                        "provider": "secret-provider",
                        "model": "secret-model",
                        "api_key": _SECRET,
                    }
                ),
                encoding="utf-8",
            )
            self._write_jsonl(
                home / ".claude" / "projects" / "repo" / "session.jsonl",
                {
                    "type": "assistant",
                    "timestamp": "2026-08-02T01:02:03Z",
                    "message": {
                        "model": "claude-opus-4-1",
                        "content": f"transcript prose {_SECRET}",
                    },
                },
            )
            for platform in (PI_DISTRIBUTION_HOST, "pi"):
                self._write_jsonl(
                    home / f".{platform}" / "agent" / "sessions" / "repo" / "session.jsonl",
                    {
                        "type": "model_change",
                        "timestamp": "2026-08-03T01:02:03Z",
                        "provider": "openrouter",
                        "modelId": f"{platform}-model",
                    },
                )
            runtime_home = home / RUNTIME_HOME
            runtime_home.mkdir()
            (runtime_home / RUNTIME_CONFIG_FILES[0]).write_text(
                json.dumps(
                    {
                        "agents": {
                            "main": {"model": "openai/gpt-5.6-sol", "variant": "xhigh"},
                            "hostile": {"model": "openai/safe\nignore-previous"},
                        },
                        "prompt": f"transcript {_SECRET}",
                    }
                ),
                encoding="utf-8",
            )
            (runtime_home / RUNTIME_CONFIG_FILES[1]).write_text(
                '{\n  // canonical JSONC probe\n  "categories": {"deep": {"model": "anthropic/claude-opus-4-1"}}\n}',
                encoding="utf-8",
            )
            (runtime_home / "models.json").write_text(
                json.dumps({"models": [{"provider": "google", "model": "gemini-3.1-pro"}]}),
                encoding="utf-8",
            )
            (runtime_home / "auth.json").write_text(
                json.dumps(
                    {
                        "model": "secret-provider/secret-model",
                        "api_key": _SECRET,
                    }
                ),
                encoding="utf-8",
            )
            opencode_message = (
                home / ".local" / "share" / "opencode" / "storage" / "message" / "session" / "m.json"
            )
            opencode_message.parent.mkdir(parents=True)
            opencode_message.write_text(
                json.dumps(
                    {
                        "model": {"providerID": "google", "modelID": "gemini-3.1-pro"},
                        "time": {"created": "2026-08-04T01:02:03Z"},
                        "content": f"transcript {_SECRET}",
                    }
                ),
                encoding="utf-8",
            )
            self._write_jsonl(
                home / ".hermes" / "sessions" / "session.jsonl",
                {
                    "type": "model_change",
                    "timestamp": "2026-08-05T01:02:03Z",
                    "provider": "nous",
                    "model": "hermes-4",
                    "prompt": f"transcript {_SECRET}",
                },
            )

            inventory = local_model_inventory(home)

        discovery = inventory["model_discovery"]
        self.assertEqual(discovery["schema_version"], "model_discovery/v1")
        self.assertEqual(
            set(discovery["sources"]),
            {"codex", "claude-code", PI_DISTRIBUTION_HOST, "pi", RUNTIME_CONFIG_SOURCE, "opencode", "hermes", PI_FORK_HOST},
        )
        observations = discovery["observations"]
        observed = {
            (entry["source"], entry["provider"], entry["model_id"], entry["status"])
            for entry in observations
        }
        self.assertIn(("codex", "openai", "gpt-5.6-sol", "observed_before"), observed)
        self.assertIn(("claude-code", "anthropic", "claude-opus-4-1", "observed_before"), observed)
        self.assertIn((PI_DISTRIBUTION_HOST, "openrouter", f"{PI_DISTRIBUTION_HOST}-model", "observed_before"), observed)
        self.assertIn(("pi", "openrouter", "pi-model", "observed_before"), observed)
        self.assertIn((RUNTIME_CONFIG_SOURCE, "openai", "gpt-5.6-sol", "confirmed_active"), observed)
        self.assertIn(("opencode", "google", "gemini-3.1-pro", "observed_before"), observed)
        self.assertIn(("hermes", "nous", "hermes-4", "observed_before"), observed)
        serialized = json.dumps(discovery)
        self.assertNotIn(_SECRET, serialized)
        self.assertNotIn("transcript prose", serialized)
        self.assertNotIn("ignore-previous", serialized)
        self.assertNotIn("secret-provider", serialized)
        self.assertNotIn(str(home), serialized)
        self.assertTrue(all(source["fingerprint"] for source in discovery["sources"].values()))

    def test_unknown_omp_layout_is_explicitly_unverified(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".omp" / "unknown").mkdir(parents=True)
            (home / ".omp" / "unknown" / "models.json").write_text(
                json.dumps({"model": "must/not-be-read"}),
                encoding="utf-8",
            )
            discovery = local_model_inventory(home)["model_discovery"]
        self.assertEqual(discovery["sources"][PI_FORK_HOST]["status"], "layout_unverified")
        self.assertFalse(any(entry["source"] == PI_FORK_HOST for entry in discovery["observations"]))

    def test_fork_host_sessions_yield_model_changes_and_assistant_models_only(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            self._write_jsonl(
                home / PI_FORK_HOME / "agent" / "sessions" / "-work-repo" / "2026_s1.jsonl",
                {"type": "session", "id": "s1", "cwd": f"/{_SECRET}"},
                {"type": "model_change", "timestamp": "2026-02-16T10:21:30.000Z", "model": "openai/gpt-4o"},
                {"type": "thinking_level_change", "thinkingLevel": "high"},
                {
                    "type": "message",
                    "timestamp": "2026-02-16T10:22:00.000Z",
                    "message": {
                        "role": "assistant",
                        "provider": "anthropic",
                        "model": "claude-sonnet-4-5",
                        "content": [{"type": "text", "text": f"transcript {_SECRET}"}],
                    },
                },
                {"type": "message", "message": {"role": "user", "content": f"prompt {_SECRET}"}},
                {"type": "model_change", "model": "no-provider-separator"},
            )
            discovery = local_model_inventory(home)["model_discovery"]
        source = discovery["sources"][PI_FORK_HOST]
        self.assertEqual(source["status"], "observed_before")
        self.assertTrue(source["supported_root"])
        observed = {
            (entry["source"], entry["provider"], entry["model_id"])
            for entry in discovery["observations"]
            if entry["source"] == PI_FORK_HOST
        }
        self.assertEqual(observed, {(PI_FORK_HOST, "openai", "gpt-4o"), (PI_FORK_HOST, "anthropic", "claude-sonnet-4-5")})
        self.assertNotIn(_SECRET, json.dumps(discovery))

    def test_discovery_rejects_symlinks_to_credentials_outside_fixed_roots(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            outside = Path(tmp) / "credentials"
            outside.mkdir(parents=True)
            leaked_record = json.dumps(
                {
                    "type": "model_change",
                    "provider": "nous",
                    "model": "leaked-model-42",
                    "api_key": _SECRET,
                }
            )
            (outside / "session.jsonl").write_text(leaked_record + "\n", encoding="utf-8")

            codex_root = home / ".codex"
            codex_root.mkdir(parents=True)
            (codex_root / "sessions").symlink_to(outside, target_is_directory=True)
            hermes_root = home / ".hermes" / "sessions"
            hermes_root.mkdir(parents=True)
            (hermes_root / "leak.jsonl").symlink_to(outside / "session.jsonl")

            discovery = local_model_inventory(home)["model_discovery"]

        serialized = json.dumps(discovery)
        self.assertNotIn(_SECRET, serialized)
        self.assertNotIn("leaked-model-42", serialized)
        self.assertFalse(
            any(entry["source"] in {"codex", "hermes"} for entry in discovery["observations"])
        )

    def test_jsonl_stops_reading_when_record_limit_is_reached(self) -> None:
        class ReadlineBudget(io.BytesIO):
            def __init__(self, initial_bytes: bytes, *, allowed_reads: int) -> None:
                super().__init__(initial_bytes)
                self.allowed_reads = allowed_reads
                self.readline_calls = 0

            def readline(self, size: int = -1, /) -> bytes:
                self.readline_calls += 1
                if self.readline_calls > self.allowed_reads:
                    raise AssertionError("JSONL discovery buffered records beyond its limit")
                return super().readline(size)

        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            session = home / ".codex" / "sessions" / "large.jsonl"
            self._write_jsonl(
                session,
                {
                    "type": "session_meta",
                    "payload": {"model_provider": "openai", "model": "first"},
                },
            )
            record = (
                json.dumps(
                    {
                        "type": "session_meta",
                        "payload": {"model_provider": "openai", "model": "streamed"},
                    }
                ).encode()
                + b"\n"
            )
            guarded = ReadlineBudget(record * 100_000, allowed_reads=1)
            original_open = Path.open

            def guarded_open(path: Path, *args: object, **kwargs: object) -> object:
                if path == session:
                    return guarded
                return original_open(path, *args, **kwargs)

            with mock.patch.object(Path, "open", new=guarded_open):
                discovery = local_model_inventory(
                    home,
                    discovery_limits={"max_records_per_source": 1},
                )["model_discovery"]

        source = discovery["sources"]["codex"]
        self.assertEqual(source["scanned_records"], 1)
        self.assertIn("record_count", source["truncated_reasons"])
        self.assertEqual(guarded.readline_calls, 1)

    def test_count_depth_size_and_deadline_limits_report_truncated(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            codex_root = home / ".codex" / "sessions"
            for index in range(2):
                self._write_jsonl(
                    codex_root / f"{index}.jsonl",
                    {
                        "type": "session_meta",
                        "payload": {"model_provider": "openai", "model": f"gpt-{index}"},
                    },
                )
            deep = home / ".claude" / "projects"
            for segment in range(9):
                deep /= str(segment)
            self._write_jsonl(deep / "session.jsonl", {"message": {"model": "claude-deep"}})
            self._write_jsonl(
                home / PI_DISTRIBUTION_HOME / "agent" / "sessions" / "oversized.jsonl",
                {
                    "type": "model_change",
                    "provider": "openrouter",
                    "modelId": "x" * 70_000,
                },
            )
            inventory = local_model_inventory(
                home,
                discovery_limits={
                    "max_records_per_source": 1,
                    "max_record_bytes": 65_536,
                    "max_depth": 8,
                    "soft_budget_seconds": 5.0,
                },
            )
        sources = inventory["model_discovery"]["sources"]
        self.assertEqual(sources["codex"]["status"], "truncated")
        self.assertEqual(sources["claude-code"]["status"], "truncated")
        self.assertEqual(sources[PI_DISTRIBUTION_HOST]["status"], "truncated")
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            self._write_jsonl(
                home / ".pi" / "agent" / "sessions" / "deadline.jsonl",
                {"type": "model_change", "provider": "openrouter", "modelId": "pi-model"},
            )
            clock_values = iter((0.0, 0.0, 0.0, 0.0, 6.0))
            deadline_inventory = local_model_inventory(
                home,
                discovery_limits={"soft_budget_seconds": 5.0},
                discovery_clock=lambda: next(clock_values, 6.0),
            )
        self.assertEqual(
            deadline_inventory["model_discovery"]["sources"]["pi"]["status"],
            "truncated",
        )

    def test_corrupt_store_does_not_hide_other_sources(self) -> None:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            bad = home / ".codex" / "sessions" / "bad.jsonl"
            bad.parent.mkdir(parents=True)
            bad.write_text("{not-json\n", encoding="utf-8")
            self._write_jsonl(
                home / ".pi" / "agent" / "sessions" / "good.jsonl",
                {
                    "type": "model_change",
                    "provider": "openrouter",
                    "modelId": "pi-good",
                },
            )
            discovery = local_model_inventory(home)["model_discovery"]
        self.assertEqual(discovery["sources"]["codex"]["status"], "unobserved")
        self.assertEqual(discovery["sources"]["pi"]["status"], "observed_before")
        self.assertTrue(any(entry["model_id"] == "pi-good" for entry in discovery["observations"]))


class InventoryModelCatalogTests(unittest.TestCase):
    def _catalog(self) -> dict:
        with TemporaryDirectory() as tmp:
            inventory = local_model_inventory(_write_home(tmp, runtime_config=_RUNTIME_CONFIG_FIXTURE))
        catalog = inventory_model_catalog(inventory)
        assert catalog is not None
        return catalog

    def test_catalog_targets_the_pi_family_runtime_profile(self) -> None:
        catalog = self._catalog()
        self.assertEqual(catalog["schema_version"], LOCAL_MODEL_CATALOG_SCHEMA_VERSION)
        self.assertEqual(catalog["executor_profile"], MODEL_INVENTORY_CATALOG_PROFILE)
        self.assertEqual(catalog["catalog_kind"], "local_inventory")
        # The affinity vocabulary rides the catalog so routing consumes it as
        # data, never as an import.
        self.assertEqual(catalog["domain_affinities"], MODEL_DOMAIN_AFFINITIES)

    def test_chains_derive_from_category_role_sources_in_config_order(self) -> None:
        catalog = self._catalog()
        chains = catalog["chains"]
        # The fixture declares only visual-engineering; only roles sourcing it
        # gain a chain, in the config's own primary-then-fallback order.
        self.assertEqual(
            [entry["model_id"] for entry in chains["design_visual"]],
            ["opencode/gemini-3.1-pro", "anthropic/claude-opus-5"],
        )
        self.assertEqual(chains["design_visual"][0]["reasoning_effort"], "high")
        self.assertNotIn("brain", chains)
        self.assertIn("design_visual", CATEGORY_ROLE_SOURCES)

    def test_options_never_carry_effort_authority(self) -> None:
        catalog = self._catalog()
        for option in catalog["options"]:
            self.assertEqual(option["reasoning_efforts"], ())

    def test_fingerprint_is_deterministic_for_an_unchanged_config(self) -> None:
        first = self._catalog()
        second = self._catalog()
        self.assertEqual(first["fingerprint"]["digest"], second["fingerprint"]["digest"])
        self.assertIn("runtime_agent_config", first["fingerprint"]["sources"])

    def test_fingerprint_changes_when_chains_move_across_the_same_models(self) -> None:
        """The digest anchors the derived artifact: reassigning a category to
        an already-present model must change the digest even though the model
        SET is identical — that reassignment is exactly the drift the
        fingerprint exists to make visible."""
        base = {
            "categories": {
                "ultrabrain": {"model": "opencode/glm-5"},
                "quick": {"model": "opencode/gemini-3-flash"},
            }
        }
        swapped = {
            "categories": {
                "ultrabrain": {"model": "opencode/gemini-3-flash"},
                "quick": {"model": "opencode/glm-5"},
            }
        }
        digests = []
        for config in (base, swapped):
            with TemporaryDirectory() as tmp:
                inventory = local_model_inventory(_write_home(tmp, runtime_config=config))
            catalog = inventory_model_catalog(inventory)
            assert catalog is not None
            digests.append(catalog["fingerprint"]["digest"])
        self.assertNotEqual(digests[0], digests[1])

    def test_empty_inventory_yields_no_catalog(self) -> None:
        with TemporaryDirectory() as tmp:
            inventory = local_model_inventory(Path(tmp))
        self.assertIsNone(inventory_model_catalog(inventory))

    def test_fingerprint_note_reports_skew_advisorily(self) -> None:
        route = {"catalog_fingerprint": {"digest": "abc123"}}
        note = catalog_fingerprint_note(route, "abc123")
        self.assertEqual(note, {"frozen_digest": "abc123", "current_digest": "abc123", "match": True})
        drifted = catalog_fingerprint_note(route, "def456")
        self.assertFalse(drifted["match"])
        self.assertIsNone(catalog_fingerprint_note({"selected_model": "x"}, "abc123"))
        self.assertIsNone(catalog_fingerprint_note(None, "abc123"))


class ModelInventoryCliTests(unittest.TestCase):
    def test_fanout_prepare_freezes_local_route_with_fingerprint(self) -> None:
        """A unit owned by the pi-family runtime with a declared role freezes a
        route resolved from the user's own config — catalog_kind plus the
        inventory fingerprint land in the contract so the basis is named."""
        units = json.dumps(
            [
                {
                    "unit_id": "visual",
                    "title": "Visual work",
                    "owner": "pi-family-runtime",
                    "file_scope": ["src/ui/"],
                    "role": "design_visual",
                    "domain": "multimodal_vision",
                },
                {
                    "unit_id": "aux",
                    "title": "Aux",
                    "owner": "codex",
                    "file_scope": ["docs/"],
                },
            ]
        )
        with TemporaryDirectory() as tmp:
            home = _write_home(tmp, runtime_config=_RUNTIME_CONFIG_FIXTURE)
            with mock.patch.dict("os.environ", {"HOME": str(home), "USERPROFILE": str(home)}):
                status, stdout, _stderr = run_cli(
                    ["coding", "fanout", "prepare", "--goal", "ship", "the", "feature", "--units", "-"],
                    stdin_text=units,
                )
        self.assertEqual(status, 0)
        contract = json.loads(stdout)
        by_id = {unit["unit_id"]: unit for unit in contract["units"]}
        route = by_id["visual"]["handoff"]["model_route"]
        self.assertEqual(route["catalog_kind"], "local_inventory")
        self.assertEqual(route["selected_model"], "opencode/gemini-3.1-pro")
        self.assertTrue(route["catalog_fingerprint"]["digest"])
        # The declared domain rides the frozen route with its attempted trail.
        self.assertEqual(route["domain"], "multimodal_vision")
        self.assertIn("domain_affinity", [entry["stage"] for entry in route["attempted"]])
        # Built-in-catalog owners stay on built-in resolution, untouched.
        self.assertNotIn("model_route", by_id["aux"]["handoff"])

    def test_prepare_without_catalogless_owners_is_home_independent(self) -> None:
        """A codex/claude-only contract must stay byte-identical across
        machines: prepare consults the inventory only when a unit names a
        profile without a built-in catalog, so whatever local config exists
        must not leak into the contract."""
        units = json.dumps(
            [
                {"unit_id": "core", "title": "Core", "owner": "codex", "file_scope": ["src/a/"], "role": "brain"},
                {"unit_id": "aux", "title": "Aux", "owner": "claude-code", "file_scope": ["docs/"], "role": "docs"},
            ]
        )
        outputs = []
        for config in (_RUNTIME_CONFIG_FIXTURE, None):
            with TemporaryDirectory() as tmp:
                home = _write_home(tmp, runtime_config=config) if config else Path(tmp)
                with mock.patch.dict("os.environ", {"HOME": str(home), "USERPROFILE": str(home)}):
                    status, stdout, _stderr = run_cli(
                        ["coding", "fanout", "prepare", "--goal", "ship", "it", "--units", "-"],
                        stdin_text=units,
                    )
            self.assertEqual(status, 0)
            outputs.append(stdout)
        self.assertEqual(outputs[0], outputs[1])

    def test_model_route_cli_from_inventory_flag(self) -> None:
        with TemporaryDirectory() as tmp:
            home = _write_home(tmp, runtime_config=_RUNTIME_CONFIG_FIXTURE)
            with mock.patch.dict("os.environ", {"HOME": str(home), "USERPROFILE": str(home)}):
                status, stdout, _stderr = run_cli(
                    [
                        "coding",
                        "model-route",
                        "--executor",
                        "pi-family-runtime",
                        "--role",
                        "design_visual",
                        "--from-inventory",
                        "--json",
                    ]
                )
        self.assertEqual(status, 0)
        route = json.loads(stdout)
        self.assertEqual(route["status"], "routed")
        self.assertEqual(route["catalog_kind"], "local_inventory")
        self.assertEqual(route["selected_model"], "opencode/gemini-3.1-pro")

    def test_cli_plain_text_default_and_json_optin(self) -> None:
        with TemporaryDirectory() as tmp:
            home = _write_home(tmp, runtime_config=_RUNTIME_CONFIG_FIXTURE)
            with mock.patch.dict("os.environ", {"HOME": str(home), "USERPROFILE": str(home)}):
                status, stdout, _stderr = run_cli(
                    ["coding", "model-inventory"], output_json=False
                )
                self.assertEqual(status, 0)
                self.assertIn("Local model inventory", stdout)
                self.assertIn("opencode/kimi-k3 [kimi]", stdout)
                self.assertIn("x_platform_data work favors grok", stdout)
                status, stdout, _stderr = run_cli(["coding", "model-inventory", "--json"])
                self.assertEqual(status, 0)
                payload = json.loads(stdout)
        self.assertEqual(payload["schema_version"], MODEL_INVENTORY_SCHEMA_VERSION)
        self.assertTrue(payload["available_models"])


if __name__ == "__main__":
    unittest.main()
