"""`omh_delegate_route` only routes to a provider the person configured.

The `provider` argument is model-supplied, and routing/model-providers.json
is a file a model with a file tool can write. Either one names where the
next delegated child sends its whole task, so a provider the person never
linked to Hermes is refused with config.yaml untouched -- for `set` with an
explicit provider and for a `fallback` candidate resolved from routes.

Every test passes explicit temporary homes; nothing here reads or writes the
developer's own `~/.hermes` or `~/.omh`.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from omh.plugin_bundle.omh.delegation_routing import read_delegation_route
from omh.plugin_bundle.omh.hermes_delegation import (
    HERMES_MIXTURE_CATEGORY_CHAINS,
    MODEL_PROVIDER_ROUTES_SCHEMA_VERSION,
    PROVIDER_ENTITLEMENTS_SCHEMA_VERSION,
    alias_is_served,
    effective_mixture_category_chains,
    model_provider_routes_path,
    provider_entitlements_path,
)
from omh.plugin_bundle.omh.tools.delegate_route_tool import omh_delegate_route_handler

SESSION_CONFIG = (
    "model:\n"
    "  provider: anthropic\n"
    "delegation:\n"
    "  max_concurrent_children: 4\n"
)


class ProviderConsentTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.hermes_home = root / "hermes"
        self.omh_home = root / "omh"
        self.hermes_home.mkdir()
        self.omh_home.mkdir()
        self.config = self.hermes_home / "config.yaml"
        self.config.write_text(SESSION_CONFIG, encoding="utf-8")

    def call(self, **args) -> dict:
        return json.loads(
            omh_delegate_route_handler(
                {"hermes_home": str(self.hermes_home), "omh_home": str(self.omh_home), **args},
                session_id="consent-session",
                task_id="consent-task",
            )
        )

    def write_routing(self, name: str, document: dict) -> None:
        path = self.omh_home / "routing" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document), encoding="utf-8")

    def test_an_unconfigured_explicit_provider_is_refused_and_nothing_is_written(self) -> None:
        before = self.config.read_bytes()

        result = self.call(action="set", model="some-model", provider="openrouter")

        self.assertEqual(result["status"], "error")
        self.assertIn("'openrouter'", result["error"])
        self.assertIn("not one you configured", result["error"])
        self.assertEqual(result["provider"], "openrouter")
        self.assertIn("anthropic", result["configured_providers"])
        self.assertEqual(self.config.read_bytes(), before)
        self.assertFalse((self.omh_home / "routing" / "delegation-route-provenance.jsonl").exists())

    def test_a_configured_explicit_provider_still_routes(self) -> None:
        cases = {
            # A Hermes login in auth.json.
            "openai-codex": SESSION_CONFIG,
            # A named `providers:` block, addressed by its custom identity.
            "custom:opengateway": SESSION_CONFIG + (
                "providers:\n"
                "  opengateway:\n"
                "    base_url: https://gateway.example.com/v1\n"
            ),
            # A legacy `custom_providers:` list entry.
            "custom:legacy-relay": SESSION_CONFIG + (
                "custom_providers:\n"
                "  - name: Legacy Relay\n"
                "    base_url: https://relay.example.com/v1\n"
            ),
            # The session's own provider.
            "anthropic": SESSION_CONFIG,
        }
        (self.hermes_home / "auth.json").write_text(
            json.dumps({"providers": {"openai-codex": {"tokens": {"access_token": "x"}}}}),
            encoding="utf-8",
        )
        for provider, config in cases.items():
            with self.subTest(provider=provider):
                self.config.write_text(config, encoding="utf-8")
                result = self.call(action="set", model="vendor/child-model", provider=provider)
                self.assertEqual(result["status"], "routed", result.get("error"))
                self.assertEqual(read_delegation_route(self.hermes_home)["provider"], provider)
                self.assertEqual(self.call(action="clear")["status"], "cleared")

    def test_a_category_head_routed_to_an_unconfigured_provider_is_refused(self) -> None:
        self.write_routing("model-chains.json", {
            "schema_version": "mixture_chain_overrides/v1",
            "categories": {"quick": [{"model": "head", "reasoning_effort": "low"}]},
        })
        self.write_routing("model-providers.json", {
            "schema_version": "model_provider_routes/v1",
            "models": {"head": {"provider": "openrouter", "model": "vendor/head"}},
        })
        before = self.config.read_bytes()

        result = self.call(action="set", category="quick")

        self.assertEqual(result["status"], "error")
        self.assertIn("model-providers.json", result["error"])
        self.assertEqual(self.config.read_bytes(), before)

    def test_fallback_passes_over_a_candidate_on_an_unconfigured_provider(self) -> None:
        self.write_routing("model-chains.json", {
            "schema_version": "mixture_chain_overrides/v1",
            "categories": {"quick": [
                {"model": "head", "reasoning_effort": "low"},
                {"model": "egress", "reasoning_effort": "low"},
                {"model": "safe", "reasoning_effort": "low"},
            ]},
        })
        self.write_routing("model-providers.json", {
            "schema_version": "model_provider_routes/v1",
            "models": {
                "head": {"provider": "anthropic", "model": "vendor/head"},
                "egress": {"provider": "openrouter", "model": "vendor/egress"},
                "safe": {"provider": "anthropic", "model": "vendor/safe"},
            },
        })
        self.assertEqual(self.call(action="set", category="quick")["status"], "routed")

        result = self.call(action="fallback")

        # Chain shaping already sorts an entry routed to an unheld provider
        # behind the served ones, so the next candidate is `safe` and the
        # unconfigured one is never reached, let alone written.
        self.assertEqual(result["status"], "fell_back", result.get("error"))
        self.assertEqual(result["applied"]["alias"], "safe")
        route = read_delegation_route(self.hermes_home)
        self.assertEqual(route["provider"], "anthropic")
        self.assertEqual(route["model"], "vendor/safe")
        self.assertNotIn("openrouter", self.config.read_text(encoding="utf-8"))

        # From `safe` the only candidate left is the unconfigured one: it is
        # passed over, and the chain counts as exhausted instead.
        exhausted = self.call(action="fallback")
        self.assertEqual(exhausted["status"], "exhausted_to_inherit", exhausted.get("error"))
        self.assertEqual(exhausted["skipped_unconfigured"], [{"alias": "egress", "provider": "openrouter"}])
        self.assertNotIn("openrouter", self.config.read_text(encoding="utf-8"))

    def test_fallback_whose_only_candidate_is_unconfigured_never_writes_it(self) -> None:
        self.write_routing("model-chains.json", {
            "schema_version": "mixture_chain_overrides/v1",
            "categories": {"quick": [
                {"model": "head", "reasoning_effort": "low"},
                {"model": "egress", "reasoning_effort": "low"},
            ]},
        })
        self.write_routing("model-providers.json", {
            "schema_version": "model_provider_routes/v1",
            "models": {
                "head": {"provider": "anthropic", "model": "vendor/head"},
                "egress": {"provider": "openrouter", "model": "vendor/egress"},
            },
        })
        self.assertEqual(self.call(action="set", category="quick")["status"], "routed")

        result = self.call(action="fallback")

        self.assertEqual(result["status"], "exhausted_to_inherit", result.get("error"))
        self.assertEqual(result["skipped_unconfigured"], [{"alias": "egress", "provider": "openrouter"}])
        self.assertNotEqual(read_delegation_route(self.hermes_home).get("provider"), "openrouter")
        self.assertNotIn("openrouter", self.config.read_text(encoding="utf-8"))


class RouteOnlyProviderConsentTest(unittest.TestCase):
    """A relay key lets a route name its provider and enrols nothing else (#2635)."""

    PROVIDER = "commandcode"
    KEY_NAME = "COMMANDCODE_API_KEY"

    @property
    def ROUTE(self) -> dict:
        return {"action": "set", "model": "deepseek/deepseek-v4-pro", "provider": self.PROVIDER}

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.hermes_home = root / "hermes"
        self.omh_home = root / "omh"
        self.hermes_home.mkdir()
        self.omh_home.mkdir()
        self.config = self.hermes_home / "config.yaml"
        self.config.write_text(SESSION_CONFIG, encoding="utf-8")

    def env(self, text: str) -> None:
        (self.hermes_home / ".env").write_text(text, encoding="utf-8")

    def record(self, **document: object) -> None:
        path = provider_entitlements_path(self.omh_home)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schema_version": PROVIDER_ENTITLEMENTS_SCHEMA_VERSION, **document}), encoding="utf-8")

    def auth(self, **store: object) -> None:
        (self.hermes_home / "auth.json").write_text(json.dumps({"version": 1, **store}), encoding="utf-8")

    def pool(self, source: str, provider: str = "") -> None:
        self.auth(credential_pool={provider or self.PROVIDER: [{"source": source}]})

    def call(self, **route: object) -> dict:
        return json.loads(
            omh_delegate_route_handler(
                {"hermes_home": str(self.hermes_home), "omh_home": str(self.omh_home), **(route or self.ROUTE)},
                session_id="consent-session",
                task_id="consent-task",
            )
        )

    def assert_routed(self) -> None:
        payload = self.call()
        self.assertEqual(payload["status"], "routed", payload)
        route = read_delegation_route(self.hermes_home)
        self.assertEqual(route["provider"], self.PROVIDER)
        self.assertEqual(route["model"], "deepseek/deepseek-v4-pro")

    def assert_refused(self) -> None:
        before = self.config.read_bytes()
        payload = self.call()
        self.assertEqual(payload["reason"], "provider_not_configured", payload)
        self.assertEqual(self.config.read_bytes(), before)

    def test_the_key_in_env_lets_a_route_name_the_provider(self) -> None:
        self.env(f"{self.KEY_NAME}=placeholder-key\n")
        self.assert_routed()

    def test_a_login_or_counted_pool_row_lets_a_route_name_the_provider(self) -> None:
        for name, store in (
            ("manual", {"credential_pool": {self.PROVIDER: [{"source": "manual"}]}}),
            ("manual label", {"credential_pool": {self.PROVIDER: [{"source": "manual:work"}]}}),
            ("active provider", {"active_provider": self.PROVIDER}),
            ("provider state", {"providers": {self.PROVIDER: {"token_type": "key"}}}),
        ):
            with self.subTest(name):
                self.auth(**store)
                self.assert_routed()

    def test_a_pool_row_hermes_would_not_count_is_refused(self) -> None:
        # A row seeded from a variable that is gone, and one borrowed from
        # another CLI, are not credentials the person gave Hermes.
        for source in (f"env:{self.KEY_NAME}", "gh_cli"):
            with self.subTest(source):
                self.pool(source)
                self.assert_refused()

    def test_an_env_seeded_row_lapses_with_an_empty_key(self) -> None:
        self.pool(f"env:{self.KEY_NAME}")
        self.env(f"{self.KEY_NAME}=\n")
        self.assert_refused()

    def test_an_excluded_provider_is_refused_with_a_pool_row(self) -> None:
        self.pool("manual")
        self.record(providers={"anthropic": "anthropic"}, excluded_providers=[self.PROVIDER])
        self.assert_refused()

    def test_a_pool_row_for_a_provider_outside_the_table_is_refused(self) -> None:
        # The auth store is read for the route-only providers, not as a new
        # way to enrol any id it holds.
        self.pool("manual", provider="other-relay")
        payload = self.call(action="set", model="deepseek/deepseek-v4-pro", provider="other-relay")
        self.assertEqual(payload["reason"], "provider_not_configured", payload)

    def test_no_env_file_is_refused(self) -> None:
        self.assert_refused()

    def test_a_key_only_exported_in_the_shell_is_refused(self) -> None:
        # Provider detection reads what Hermes recorded, never this process.
        with patch.dict("os.environ", {self.KEY_NAME: "placeholder-key"}):
            self.assert_refused()

    def test_a_commented_key_is_refused(self) -> None:
        self.env(f"# {self.KEY_NAME}=placeholder-key\n")
        self.assert_refused()

    def test_an_empty_key_is_refused(self) -> None:
        # Hermes raises "No usable credentials" on it, after OMH said routed.
        for line in (f"{self.KEY_NAME}=\n", f'{self.KEY_NAME}=""\n', f"{self.KEY_NAME}=''\n"):
            with self.subTest(line=line):
                self.env(line)
                self.assert_refused()

    def test_a_name_hermes_does_not_read_for_the_provider_is_refused(self) -> None:
        # Hermes' registry reads one key per relay: models.dev's CMD_API_KEY
        # is not commandcode's, and one relay's key never opens another.
        for name in sorted({"CMD_API_KEY", "COMMANDCODE_API_KEY", "KILOCODE_API_KEY", "AI_GATEWAY_API_KEY"} - {self.KEY_NAME}):
            with self.subTest(name):
                self.env(f"{name}=placeholder-key\n")
                self.assert_refused()

    def test_an_excluded_provider_is_refused_with_the_key_present(self) -> None:
        self.env(f"{self.KEY_NAME}=placeholder-key\n")
        self.record(providers={"anthropic": "anthropic"}, excluded_providers=[self.PROVIDER])
        self.assert_refused()

    def test_a_recorded_gateway_does_not_cover_the_key(self) -> None:
        # An env row of kind `gateway` was dropped as already held when the
        # document recorded a gateway of its own, which refused this route.
        self.env(f"{self.KEY_NAME}=placeholder-key\n")
        self.record(providers={"og": "gateway"})
        self.assert_routed()

    def routed_categories(self) -> int:
        """Categories an `anthropic` session holding its own key routes, with no routes document."""
        original = self.config.read_bytes()
        routed = 0
        for category in sorted(effective_mixture_category_chains(self.omh_home, self.hermes_home)):
            self.config.write_bytes(original)
            routed += self.call(action="set", category=category)["status"] == "routed"
        self.config.write_bytes(original)
        return routed

    def test_the_key_or_a_login_leaves_category_routes_as_they_were(self) -> None:
        # As a `gateway` account the relay served every alias, so the chains
        # fell back to the shipped order and categories whose new head the
        # session provider cannot serve were refused.
        self.env("ANTHROPIC_API_KEY=placeholder-key\n")
        baseline = self.routed_categories()
        self.assertGreater(baseline, 0)
        for label, key_line, store in (
            ("key", f"{self.KEY_NAME}=placeholder-key\n", None),
            ("manual row", "", {"credential_pool": {self.PROVIDER: [{"source": "manual"}]}}),
            ("active provider", "", {"active_provider": self.PROVIDER}),
            ("provider state", "", {"providers": {self.PROVIDER: {"token_type": "key"}}}),
        ):
            with self.subTest(label):
                self.env("ANTHROPIC_API_KEY=placeholder-key\n" + key_line)
                (self.hermes_home / "auth.json").unlink(missing_ok=True)
                if store is not None:
                    self.auth(**store)
                self.assertEqual(self.routed_categories(), baseline)

    def test_a_routes_document_sends_category_heads_to_the_held_relay(self) -> None:
        # The routes document recommended for a relay: every chain alias the
        # session's own provider cannot serve goes to it. Held, those heads
        # lead their chains again and route to the relay; not held, none does.
        anthropic_only = {"providers": {"anthropic": "anthropic"}, "subscription_clis": []}
        chains = HERMES_MIXTURE_CATEGORY_CHAINS
        aliases = sorted({alias for chain in chains.values() for alias, _effort in chain if not alias_is_served(alias, anthropic_only)})
        path = model_provider_routes_path(self.omh_home)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": MODEL_PROVIDER_ROUTES_SCHEMA_VERSION,
                    "models": {alias: {"provider": self.PROVIDER, "model": f"vendor/{alias}"} for alias in aliases},
                }
            ),
            encoding="utf-8",
        )
        original = self.config.read_bytes()
        for label, key_line in (("key", f"{self.KEY_NAME}=placeholder-key\n"), ("no key", "")):
            with self.subTest(label):
                self.env("ANTHROPIC_API_KEY=placeholder-key\n" + key_line)
                via_relay = 0
                for category in sorted(effective_mixture_category_chains(self.omh_home, self.hermes_home)):
                    self.config.write_bytes(original)
                    if self.call(action="set", category=category)["status"] == "routed":
                        via_relay += read_delegation_route(self.hermes_home).get("provider") == self.PROVIDER
                self.config.write_bytes(original)
                shipped_heads_on_relay = sum(chain[0][0] in aliases for chain in chains.values())
                self.assertGreater(shipped_heads_on_relay, 0)
                self.assertEqual(via_relay, shipped_heads_on_relay if key_line else 0)


class KilocodeRouteOnlyConsentTest(RouteOnlyProviderConsentTest):
    PROVIDER = "kilocode"
    KEY_NAME = "KILOCODE_API_KEY"


class AiGatewayRouteOnlyConsentTest(RouteOnlyProviderConsentTest):
    PROVIDER = "ai-gateway"
    KEY_NAME = "AI_GATEWAY_API_KEY"


if __name__ == "__main__":
    unittest.main()
