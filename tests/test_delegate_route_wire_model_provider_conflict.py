"""A wire id and the provider that serves it cannot be split by a `set`.

`routing/model-providers.json` records the wire id a proxy serves for each
alias. An explicit `provider` argument wins over that document by design, so
an alias may be pinned to another provider a person holds. A *wire id* is not
an alias: `ANT-claude-opus-5-5` is the proxy's own name for the model the
document already places on `opencodex`, and no other provider serves that
string.

Observed live before this gate: `set model=ANT-claude-opus-5-5
provider=openai-codex` was accepted, the pair reached `config.yaml`, and every
delegated child of that window died in seconds with `HTTP 400 ... not
supported when using Codex with a ChatGPT account`.

Nothing here reads or writes the developer's own `~/.hermes` or `~/.omh`.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from omh.plugin_bundle.omh.delegation_routing import read_delegation_route
from omh.plugin_bundle.omh.tools.delegate_route_tool import omh_delegate_route_handler

SESSION_CONFIG = (
    "model:\n"
    "  provider: anthropic\n"
    "delegation:\n"
    "  max_concurrent_children: 4\n"
    "providers:\n"
    "  opencodex:\n"
    "    base_url: http://127.0.0.1:10100/v1\n"
)


class WireModelProviderConflictTest(unittest.TestCase):
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
        (self.hermes_home / "auth.json").write_text(
            json.dumps({"providers": {"openai-codex": {"tokens": {"access_token": "x"}}}}),
            encoding="utf-8",
        )
        self.write_routing("model-providers.json", {
            "schema_version": "model_provider_routes/v1",
            "models": {"claude-opus-5-5": {"provider": "opencodex", "model": "ANT-claude-opus-5-5"}},
        })

    def call(self, **args) -> dict:
        return json.loads(
            omh_delegate_route_handler(
                {"hermes_home": str(self.hermes_home), "omh_home": str(self.omh_home), **args},
                session_id="conflict-session",
                task_id="conflict-task",
            )
        )

    def write_routing(self, name: str, document: dict) -> None:
        path = self.omh_home / "routing" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document), encoding="utf-8")

    def test_a_wire_id_pinned_to_another_provider_is_refused_and_nothing_is_written(self) -> None:
        before = self.config.read_bytes()

        result = self.call(action="set", model="ANT-claude-opus-5-5", provider="openai-codex", reasoning_effort="medium")

        self.assertEqual(result["status"], "error", result)
        self.assertIn("ANT-claude-opus-5-5", result["error"])
        self.assertIn("opencodex", result["error"])
        self.assertEqual(result["providers_serving_model"], ["opencodex"])
        self.assertEqual(self.config.read_bytes(), before)

    def test_the_same_wire_id_with_its_own_provider_routes(self) -> None:
        result = self.call(action="set", model="ANT-claude-opus-5-5", provider="opencodex", reasoning_effort="medium")

        self.assertEqual(result["status"], "routed", result.get("error"))
        self.assertEqual(read_delegation_route(self.hermes_home)["provider"], "opencodex")
        self.assertEqual(read_delegation_route(self.hermes_home)["model"], "ANT-claude-opus-5-5")

    def test_an_alias_may_still_be_pinned_to_another_provider(self) -> None:
        """The documented override stays open: an alias is not a wire id."""

        result = self.call(action="set", model="claude-opus-5-5", provider="anthropic")

        self.assertEqual(result["status"], "routed", result.get("error"))
        self.assertEqual(read_delegation_route(self.hermes_home)["provider"], "anthropic")
        self.assertEqual(read_delegation_route(self.hermes_home)["model"], "claude-opus-5-5")

    def test_a_wire_id_no_route_describes_is_dispatched_unchanged(self) -> None:
        result = self.call(action="set", model="vendor/child-model", provider="openai-codex")

        self.assertEqual(result["status"], "routed", result.get("error"))
        self.assertEqual(read_delegation_route(self.hermes_home)["provider"], "openai-codex")


if __name__ == "__main__":
    unittest.main()
