"""A dispatch may not inherit a provider that cannot serve the model it pins.

Observed live: a Fable alias was pinned with no provider, inherited an
`openai-codex` session, and every dispatch returned HTTP 400. It happened
twice before the operator worked out that the model needed a different
provider and hunted its wire id down by hand. Nothing in OMH had checked the
one thing it could check -- that the provider about to serve the run is one
the catalog says can serve that model -- even though the alias and the
provider are both in scope at the moment the route is written.

These tests pin the guard and, just as importantly, its silence: it refuses
only what is known wrong, and says who could serve the model instead.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from omh.plugin_bundle.omh.delegation_routing import read_delegation_route
from omh.plugin_bundle.omh.tools.delegate_route_tool import omh_delegate_route_handler

DIRECTSDK = "claude-subscription-directsdk-experimental"


class ProviderInheritanceGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        self.config = self.home / "config.yaml"
        self.omh_home = self.home / ".omh"

    def _session_on(self, provider: str) -> None:
        self.config.write_text(f"model:\n  provider: {provider}\n", encoding="utf-8")

    def _entitlements(self, providers: dict[str, str]) -> None:
        path = self.omh_home / "routing" / "providers.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({
                "schema_version": "provider_entitlements/v1",
                "providers": providers,
                "subscription_clis": [],
            }),
            encoding="utf-8",
        )

    def _call(self, **args) -> dict:
        return json.loads(
            omh_delegate_route_handler(
                {"hermes_home": str(self.home), "omh_home": str(self.omh_home), **args}
            )
        )

    def test_the_incident_is_refused_with_the_provider_that_could_serve_it(self) -> None:
        self._session_on("openai-codex")
        self._entitlements({"og": "gateway", "openai-codex": "openai-codex"})
        result = self._call(action="set", model="claude-fable-5-1", reasoning_effort="high")
        self.assertEqual(result["status"], "error")
        self.assertIn("openai-codex", result["error"])
        self.assertIn("does not serve it", result["error"])
        self.assertEqual(result["inherited_provider"], "openai-codex")
        # The refusal is only half the help; the answer is the other half.
        self.assertEqual(result["providers_serving_alias"], ["og"])
        self.assertIn("og", result["error"])
        # Nothing was written: a refused route must not leave a half-route.
        self.assertNotIn("delegation:", self.config.read_text(encoding="utf-8"))

    def test_it_still_catches_the_incident_with_no_entitlements_recorded(self) -> None:
        # The provider id is itself a catalog family name, so the check holds
        # on an install that never ran the entitlement interview -- which is
        # the install the incident happened on.
        self._session_on("openai-codex")
        result = self._call(action="set", model="claude-fable-5-1")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["providers_serving_alias"], [])
        self.assertIn("routing/model-providers.json", result["error"])

    def test_an_explicit_provider_is_never_second_guessed(self) -> None:
        # The provider must be one the person configured; the serving check
        # still never second-guesses it.
        self._session_on("openai-codex")
        self._entitlements({"og": "gateway"})
        result = self._call(
            action="set",
            model="anthropic/claude-fable-5-1",
            provider="og",
            reasoning_effort="high",
        )
        self.assertEqual(result["status"], "routed")

    def test_a_provider_that_serves_the_alias_dispatches(self) -> None:
        self._session_on("anthropic")
        result = self._call(action="set", model="claude-fable-5-1")
        self.assertEqual(result["status"], "routed")

    def test_silence_on_every_unknown(self) -> None:
        # Nothing is refused on a guess. Each of these leaves the answer
        # genuinely unknown, and an unknown provider must never be treated as
        # a wrong one.
        cases = {
            "no session provider recorded": ("", "claude-fable-5-1", {}),
            "a model the catalog never described": ("openai-codex", "some-local-model", {}),
            "a provider id nothing records": ("my-own-thing", "claude-fable-5-1", {}),
        }
        for label, (session_provider, model, providers) in cases.items():
            with self.subTest(case=label):
                self.config.write_text(
                    f"model:\n  provider: {session_provider}\n" if session_provider else "model:\n",
                    encoding="utf-8",
                )
                if providers:
                    self._entitlements(providers)
                result = self._call(action="set", model=model)
                self.assertEqual(result["status"], "routed", result)

    def _directsdk_plugin(self) -> None:
        plugin = self.home / "plugins" / "directsdk"
        plugin.mkdir(parents=True)
        (plugin / "plugin.yaml").write_text(f"name: {DIRECTSDK}\nkind: model-provider\n", encoding="utf-8")
        (plugin / "__init__.py").write_text("", encoding="utf-8")

    def _pinned(self, model: str = "claude-opus-5-5") -> str:
        result = self._call(action="set", model=model)
        self.assertEqual(result["status"], "routed", result)
        return result["provider_pinned"]["pinned_provider"]

    def test_an_installed_claude_provider_plugin_is_pinned_for_a_claude_alias(self) -> None:
        # Nothing recorded: the DirectSDK provider plugin alone is the one
        # provider known to serve a Claude alias, so a route with no
        # provider is pinned to it instead of inheriting `openai-codex`.
        self._session_on("openai-codex")
        self._directsdk_plugin()
        result = self._call(action="set", model="claude-opus-5-5")
        self.assertEqual(result["status"], "routed", result)
        self.assertEqual(
            result["provider_pinned"],
            {"inherited_provider": "openai-codex", "pinned_provider": DIRECTSDK},
        )
        self.assertEqual(
            read_delegation_route(self.home),
            {"model": "claude-opus-5-5", "provider": DIRECTSDK},
        )

    # Another Claude provider beside the plugin: (setup, provider pinned
    # before the plugin was detected, whether it can be excluded -- only a
    # linked provider can; a recorded one is cleared by editing the record).
    _CLAUDE_BESIDE_PLUGIN = {
        "an Anthropic login": ("login", "anthropic", True),
        "an Anthropic key": ("key", "anthropic", True),
        "a recorded ccapi": ("ccapi", "ccapi", False),
        "a recorded anthropic": ("anthropic", "anthropic", False),
    }

    def _claude_beside_plugin(self, setup: str, *, excluded: str = "", route: bool = False) -> None:
        self._tmp = tempfile.TemporaryDirectory()  # a fresh home per case
        self.addCleanup(self._tmp.cleanup)
        self.home = Path(self._tmp.name)
        self.config = self.home / "config.yaml"
        self.omh_home = self.home / ".omh"
        self._session_on("openai-codex")
        self._directsdk_plugin()
        if setup == "login":
            (self.home / "auth.json").write_text(
                json.dumps({"version": 1, "providers": {"anthropic": {"access_token": "t"}}}), encoding="utf-8"
            )
        elif setup == "key":
            (self.home / ".env").write_text("ANTHROPIC_API_KEY=filled\n", encoding="utf-8")
        else:
            self._entitlements({setup: setup})
        if excluded:
            path = self.omh_home / "routing" / "providers.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({"schema_version": "provider_entitlements/v1", "excluded_providers": [excluded]}),
                encoding="utf-8",
            )
        if route:
            path = self.omh_home / "routing" / "model-providers.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps({
                    "schema_version": "model_provider_routes/v1",
                    "models": {"claude-opus-5-5": {"provider": DIRECTSDK, "model": "claude-opus-5-5"}},
                }),
                encoding="utf-8",
            )

    def test_installing_the_plugin_keeps_the_existing_claude_pin(self) -> None:
        # Before the plugin was detected each of these pinned the other
        # provider. Two pinnable providers would be a refusal; the one found
        # some way other than the plugin is the pin it always was.
        for label, (setup, before, _excludable) in self._CLAUDE_BESIDE_PLUGIN.items():
            with self.subTest(case=label):
                self._claude_beside_plugin(setup)
                self.assertEqual(self._pinned(), before)
                self.assertEqual(read_delegation_route(self.home)["provider"], before)

    def test_a_route_to_the_plugin_wins_over_the_other_claude_provider(self) -> None:
        for label, (setup, _before, _excludable) in self._CLAUDE_BESIDE_PLUGIN.items():
            with self.subTest(case=label):
                self._claude_beside_plugin(setup, route=True)
                result = self._call(action="set", model="claude-opus-5-5")
                self.assertEqual(result["status"], "routed", result)
                self.assertNotIn("provider_pinned", result)
                self.assertEqual(read_delegation_route(self.home)["provider"], DIRECTSDK)

    def test_an_explicit_plugin_provider_is_not_refused(self) -> None:
        for label, (setup, _before, _excludable) in self._CLAUDE_BESIDE_PLUGIN.items():
            with self.subTest(case=label):
                self._claude_beside_plugin(setup)
                result = self._call(action="set", model="claude-opus-5-5", provider=DIRECTSDK)
                self.assertEqual(result["status"], "routed", result)
                self.assertEqual(read_delegation_route(self.home)["provider"], DIRECTSDK)

    def test_excluding_the_other_claude_provider_makes_the_plugin_the_pin(self) -> None:
        for label, (setup, before, excludable) in self._CLAUDE_BESIDE_PLUGIN.items():
            if not excludable:
                continue
            with self.subTest(case=label):
                self._claude_beside_plugin(setup, excluded=before)
                self.assertEqual(self._pinned(), DIRECTSDK)

    def test_a_tie_of_providers_neither_recorded_nor_plugin_only_still_refuses(self) -> None:
        # Two linked Claude providers: nothing says which one the operator
        # prefers, so the guard refuses as it always did.
        self._session_on("openai-codex")
        self._directsdk_plugin()
        (self.home / "auth.json").write_text(
            json.dumps({"version": 1, "providers": {"anthropic": {"access_token": "t"}}}), encoding="utf-8"
        )
        self.config.write_text(
            "model:\n  provider: openai-codex\nproviders:\n  my-anthropic:\n    base_url: https://api.anthropic.com/v1\n",
            encoding="utf-8",
        )
        result = self._call(action="set", model="claude-opus-5-5")
        self.assertEqual(result["status"], "error", result)
        self.assertEqual(result["providers_serving_alias"], ["anthropic", DIRECTSDK, "my-anthropic"])

    def test_the_plugin_recorded_by_hand_wins_the_tie_with_a_login(self) -> None:
        # `omh model-chains provider set <plugin> anthropic` is the one-line
        # way to prefer the subscription over a Hermes Anthropic login.
        self._session_on("openai-codex")
        self._directsdk_plugin()
        (self.home / "auth.json").write_text(
            json.dumps({"version": 1, "providers": {"anthropic": {"access_token": "t"}}}), encoding="utf-8"
        )
        self._entitlements({DIRECTSDK: "anthropic"})
        self.assertEqual(self._pinned(), DIRECTSDK)

    def test_a_recorded_provider_wins_the_tie_and_two_recorded_still_refuse(self) -> None:
        # Family-agnostic, and only ever a tie-break: a GLM alias with a
        # config `zai` block and a recorded `my-zai` pins the recorded one;
        # with both recorded there is no preference and the guard refuses.
        head = "model:\n  provider: openai-codex\nproviders:\n  zai:\n    base_url: https://api.z.ai/api/paas/v4\n"
        self.config.write_text(head, encoding="utf-8")
        self._entitlements({"my-zai": "zai"})
        self.assertEqual(self._pinned("glm-5.3"), "my-zai")
        self.config.write_text(head, encoding="utf-8")
        self._entitlements({"my-zai": "zai", "zai": "zai"})
        result = self._call(action="set", model="glm-5.3")
        self.assertEqual(result["status"], "error", result)
        self.assertEqual(result["providers_serving_alias"], ["my-zai", "zai"])
        # One pinnable provider is never touched by the tie-break.
        self.config.write_text("model:\n  provider: openai-codex\n", encoding="utf-8")
        self._entitlements({"zai": "zai"})
        self.assertEqual(self._pinned("glm-5.3"), "zai")

    def test_the_plugin_recorded_beside_anthropic_keeps_anthropic(self) -> None:
        # `omh setup` records every row it found, the plugin included, so a
        # record naming both is not a preference for the plugin: it is set
        # aside and the pin is the one the machine had without it.
        self._session_on("openai-codex")
        self._directsdk_plugin()
        self._entitlements({DIRECTSDK: "anthropic", "anthropic": "anthropic"})
        self.assertEqual(self._pinned(), "anthropic")

    def test_two_recorded_claude_providers_besides_the_plugin_still_refuse(self) -> None:
        self._session_on("openai-codex")
        self._directsdk_plugin()
        self._entitlements({DIRECTSDK: "anthropic", "anthropic": "anthropic", "ccapi": "ccapi"})
        result = self._call(action="set", model="claude-opus-5-5")
        self.assertEqual(result["status"], "error", result)
        self.assertEqual(result["providers_serving_alias"], ["anthropic", "ccapi", DIRECTSDK])

    def test_with_the_plugin_set_aside_the_one_recorded_provider_is_the_pin(self) -> None:
        # Without the plugin, a recorded `anthropic` beside a linked
        # `my-anthropic` block pins `anthropic`; recording the plugin too
        # must not change that.
        head = (
            "model:\n  provider: openai-codex\n"
            "providers:\n  my-anthropic:\n    base_url: https://api.anthropic.com/v1\n"
        )
        self.config.write_text(head, encoding="utf-8")
        self._entitlements({"anthropic": "anthropic"})
        self.assertEqual(self._pinned(), "anthropic")
        self.config.write_text(head, encoding="utf-8")
        self._directsdk_plugin()
        self._entitlements({"anthropic": "anthropic", DIRECTSDK: "anthropic"})
        self.assertEqual(self._pinned(), "anthropic")

    def test_a_default_setup_beside_an_anthropic_login_keeps_the_anthropic_pin(self) -> None:
        # Regression: Anthropic login + plugin + session on openai-codex.
        # The setup interview pre-ticks every found row, so the default
        # answer records all three; the pin must match the same home
        # without the plugin instead of turning into a refusal.
        from omh.commands import setup as setup_module
        from omh.plugin_bundle.omh.provider_detection import LINKED_SOURCE_ENV, detect_linked_providers

        def default_setup() -> dict[str, str]:
            candidates = [
                (row["id"], row["kind"], row["evidence"] if row["source"] == LINKED_SOURCE_ENV else row["source"])
                for row in detect_linked_providers(self.home, env_names=())
            ]
            _options, preselected, kinds = setup_module._provider_entitlement_options(candidates, {}, "en")
            recorded = {provider_id: kinds[provider_id] for provider_id in preselected}
            self._entitlements(recorded)
            return recorded

        for with_plugin in (False, True):
            with self.subTest(with_plugin=with_plugin):
                self._tmp = tempfile.TemporaryDirectory()
                self.addCleanup(self._tmp.cleanup)
                self.home = Path(self._tmp.name)
                self.config = self.home / "config.yaml"
                self.omh_home = self.home / ".omh"
                self._session_on("openai-codex")
                (self.home / "auth.json").write_text(
                    json.dumps({"version": 1, "providers": {"anthropic": {"access_token": "t"}}}), encoding="utf-8"
                )
                if with_plugin:
                    self._directsdk_plugin()
                recorded = default_setup()
                expected = {"anthropic", "openai-codex"} | ({DIRECTSDK} if with_plugin else set())
                self.assertEqual(set(recorded), expected)
                self.assertEqual(self._pinned(), "anthropic")

    def test_beside_a_relay_the_plugin_is_still_the_pin(self) -> None:
        # OpenRouter serves everything as a fail-open default, never as a
        # pin, so it does not compete with the plugin.
        self._session_on("openai-codex")
        self._directsdk_plugin()
        (self.home / ".env").write_text("OPENROUTER_API_KEY=filled\n", encoding="utf-8")
        self.assertEqual(self._pinned(), DIRECTSDK)

    def test_a_session_on_the_plugin_provider_inherits_it(self) -> None:
        self._session_on(DIRECTSDK)
        self._directsdk_plugin()
        result = self._call(action="set", model="claude-opus-5-5")
        self.assertEqual(result["status"], "routed", result)
        self.assertNotIn("provider_pinned", result)

    def test_a_multi_vendor_session_provider_is_left_alone(self) -> None:
        # A relay serves models of every family, so inheriting one is not a
        # known-wrong dispatch even when the alias names other families.
        self._session_on("og")
        self._entitlements({"og": "gateway"})
        result = self._call(action="set", model="claude-fable-5-1")
        self.assertEqual(result["status"], "routed")


if __name__ == "__main__":
    unittest.main()
