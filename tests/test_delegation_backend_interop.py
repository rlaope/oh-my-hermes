"""Hermes delegation backends (0.22.5+) and OMH routing, side by side.

Hermes' `delegation.backend` decides how a child is routed. Under `default`
OMH writes `delegation.model/provider/reasoning_effort`; under `model_map`
those keys are ignored, so OMH names the user's own option instead and
writes nothing; under `profile_routes` OMH never picks a profile. These tests
pin the read-only backend reader, the option matcher, and the route tool's
answers per backend.
"""

import contextlib
import json
import tempfile
import unittest
from pathlib import Path

from _local_package import load_local_package

load_local_package()

from omh.plugin_bundle.omh.delegation_backend_mode import (  # noqa: E402
    delegation_section,
    option_chain,
    option_for,
    read_backend_mode,
)
from omh.plugin_bundle.omh.hermes_delegation import load_delegation_route_provenance  # noqa: E402
from omh.plugin_bundle.omh.tools.delegate_route_tool import omh_delegate_route_handler  # noqa: E402

# The shape Hermes' own round-trip writer emits (mapping=2, sequence=4, offset=2).
MODEL_MAP_CONFIG = """\
model:
  default: claude-opus-5-5
  provider: claude-proxy
delegation:
  backend: model_map
  max_concurrent_children: 3
  fallback_providers: [og, openrouter]
  backends:
    model_map:
      default: everyday
      options:
        - name: deep-opus
          description: 'Deep work: Opus at high'
          provider: claude-proxy
          model: claude-opus-5-5
          reasoning_effort: high
        - name: sol
          description: GPT Sol # trailing comment
          provider: openrouter
          model: openai/gpt-6.1-sol
          reasoning_effort: high
          api_key: never-copied
        - name: everyday
          description: Anything
          provider: og
          model: kimi-k3.1-pro
toolsets:
  - hermes-cli
"""

PROFILE_ROUTES_CONFIG = """\
delegation:
  backend: profile_routes
  backends:
    profile_routes:
      default: coder
      profiles:
        - name: coder
          description: Writes code
        - name: researcher
          description: Reads sources
"""


class BackendModeReaderTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)

    def _read(self, text: str) -> dict:
        (self.home / "config.yaml").write_text(text, encoding="utf-8")
        return read_backend_mode(self.home)

    def test_missing_config_and_unset_backend_read_as_default(self):
        self.assertEqual(read_backend_mode(self.home)["backend"], "default")
        mode = self._read("delegation:\n  model: ''\n  backends: {}\n")
        self.assertEqual((mode["backend"], mode["status"]), ("default", "read"))

    def test_model_map_options_read_without_credentials(self):
        mode = self._read(MODEL_MAP_CONFIG)
        self.assertEqual((mode["backend"], mode["status"], mode["default"]), ("model_map", "read", "everyday"))
        self.assertEqual([option["name"] for option in mode["options"]], ["deep-opus", "sol", "everyday"])
        self.assertEqual(mode["options"][1]["model"], "openai/gpt-6.1-sol")
        self.assertEqual(mode["options"][2]["reasoning_effort"], "")
        self.assertNotIn("never-copied", json.dumps(mode))

    def test_profile_routes_names(self):
        mode = self._read(PROFILE_ROUTES_CONFIG)
        self.assertEqual(mode["backend"], "profile_routes")
        self.assertEqual(mode["profiles"], ["coder", "researcher"])
        self.assertEqual(mode["default"], "coder")

    def test_backend_name_is_normalized(self):
        self.assertEqual(self._read("delegation:\n  backend: ' Model_Map '\n")["backend"], "model_map")

    def test_flow_options_are_unreadable_but_backend_still_known(self):
        mode = self._read(
            "delegation:\n  backend: model_map\n  backends:\n    model_map:\n"
            "      options: [{name: a, model: m}]\n"
        )
        self.assertEqual((mode["backend"], mode["status"], mode["options"]), ("model_map", "unreadable", []))

    def test_block_scalar_in_section_is_unreadable_but_backend_still_known(self):
        mode = self._read("delegation:\n  backend: model_map\n  note: |\n    text\n")
        self.assertEqual((mode["backend"], mode["status"]), ("model_map", "unreadable"))

    def test_hand_written_indentation_reads(self):
        section = delegation_section(
            "delegation:\n    backend: model_map  # mine\n    backends:\n        model_map:\n"
            "            options:\n            - name: a\n              model: m\n"
        )
        self.assertEqual(
            section,
            {"backend": "model_map", "backends": {"model_map": {"options": [{"name": "a", "model": "m"}]}}},
        )


class OptionMatcherTest(unittest.TestCase):
    OPTIONS = [
        {"name": "deep-opus", "provider": "claude-proxy", "model": "claude-opus-5-5", "reasoning_effort": "high"},
        {"name": "sol", "provider": "openrouter", "model": "openai/gpt-6.1-sol", "reasoning_effort": "high"},
        {"name": "kimi", "provider": "og", "model": "kimi-k3.1-pro", "reasoning_effort": ""},
    ]

    def test_alias_and_wire_model_match(self):
        self.assertEqual(option_for(self.OPTIONS, "claude-opus-5-5", "high"), "deep-opus")
        self.assertEqual(option_for(self.OPTIONS, "gpt-6.1-sol", "high"), "sol")

    def test_different_effort_is_not_the_same_lane(self):
        self.assertEqual(option_for(self.OPTIONS, "claude-opus-5-5", "medium"), "")

    def test_unset_option_effort_matches_any(self):
        self.assertEqual(option_for(self.OPTIONS, "kimi-k3.1-pro", "xhigh"), "kimi")

    def test_disagreeing_provider_does_not_match(self):
        self.assertEqual(option_for(self.OPTIONS, "kimi-k3.1-pro", "high", provider="openrouter"), "")

    def test_chain_keeps_order_and_drops_unserved(self):
        chain = (("claude-opus-5-5", "high"), ("gpt-6-astra", "xhigh"), ("kimi-k3.1-pro", "high"))
        self.assertEqual(
            [entry["option"] for entry in option_chain(chain, self.OPTIONS)],
            ["deep-opus", "kimi"],
        )


class RouteToolPerBackendTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.omh_home = self.home / ".omh"
        self.config = self.home / "config.yaml"

    def _call(self, **args) -> dict:
        return json.loads(
            omh_delegate_route_handler(
                {"hermes_home": str(self.home), "omh_home": str(self.omh_home), **args},
                session_id="host-session",
            )
        )

    def test_model_map_set_names_option_and_writes_nothing(self):
        self.config.write_text(MODEL_MAP_CONFIG, encoding="utf-8")
        result = self._call(action="set", category="deep")
        self.assertEqual(result["status"], "option_selected")
        self.assertEqual(result["delegation_backend"], "model_map")
        self.assertEqual(result["option"], "deep-opus")
        self.assertEqual([entry["option"] for entry in result["option_chain"]][:2], ["deep-opus", "sol"])
        self.assertEqual(self.config.read_text(encoding="utf-8"), MODEL_MAP_CONFIG)
        self.assertEqual(load_delegation_route_provenance(self.omh_home), [])
        self.assertNotIn("routed", json.dumps(result))

    def test_model_map_fallback_advances_to_next_option(self):
        self.config.write_text(MODEL_MAP_CONFIG, encoding="utf-8")
        result = self._call(action="fallback", category="deep", option="deep-opus")
        self.assertEqual((result["status"], result["option"], result["fallback_from"]), ("option_selected", "sol", "deep-opus"))

    def test_model_map_fallback_past_last_option_is_exhausted(self):
        self.config.write_text(MODEL_MAP_CONFIG, encoding="utf-8")
        chain = self._call(action="set", category="deep")["option_chain"]
        result = self._call(action="fallback", category="deep", option=chain[-1]["option"])
        self.assertEqual(result["status"], "options_exhausted")
        self.assertEqual(result["default"], "everyday")

    def test_model_map_fallback_needs_the_failed_option(self):
        self.config.write_text(MODEL_MAP_CONFIG, encoding="utf-8")
        self.assertEqual(self._call(action="fallback", category="deep")["status"], "error")

    def test_model_map_without_matching_option_is_not_applied(self):
        self.config.write_text(
            MODEL_MAP_CONFIG.replace("claude-opus-5-5\n          reasoning_effort: high", "other-model")
            .replace("openai/gpt-6.1-sol", "other/model")
            .replace("kimi-k3.1-pro", "other-kimi"),
            encoding="utf-8",
        )
        result = self._call(action="set", category="deep")
        self.assertEqual((result["status"], result["reason"]), ("not_applied", "no_matching_option"))
        self.assertEqual(result["available_options"], ["deep-opus", "sol", "everyday"])

    def test_explicit_model_matches_its_option(self):
        self.config.write_text(MODEL_MAP_CONFIG, encoding="utf-8")
        result = self._call(action="set", category="deep", model="kimi-k3.1-pro", reasoning_effort="high")
        self.assertEqual((result["status"], result["option"]), ("option_selected", "everyday"))

    def test_profile_routes_never_picks_a_profile(self):
        self.config.write_text(PROFILE_ROUTES_CONFIG, encoding="utf-8")
        result = self._call(action="set", category="deep")
        self.assertEqual((result["status"], result["reason"]), ("not_applied", "profile_routes_backend"))
        self.assertEqual(result["profiles"], ["coder", "researcher"])
        self.assertNotIn("profile", {key for key in result if key == "profile"})
        self.assertEqual(self.config.read_text(encoding="utf-8"), PROFILE_ROUTES_CONFIG)

    def test_unknown_backend_is_not_applied(self):
        text = "delegation:\n  backend: someone-elses\n"
        self.config.write_text(text, encoding="utf-8")
        result = self._call(action="set", category="deep")
        self.assertEqual((result["status"], result["reason"]), ("not_applied", "backend_not_default"))
        self.assertEqual(self.config.read_text(encoding="utf-8"), text)

    def test_status_reports_the_backend(self):
        self.config.write_text(MODEL_MAP_CONFIG, encoding="utf-8")
        backend = self._call(action="status")["delegation_backend"]
        self.assertEqual(backend["backend"], "model_map")
        self.assertEqual(backend["options"], ["deep-opus", "sol", "everyday"])

    def test_default_backend_still_writes_the_route(self):
        self.config.write_text("delegation:\n  backend: default\n  max_concurrent_children: 3\n", encoding="utf-8")
        result = self._call(action="set", category="deep")
        self.assertEqual(result["status"], "routed", result)
        self.assertIn("model: 'claude-opus-5-5'", self.config.read_text(encoding="utf-8"))


DAG_CONFIG = """\
delegation:
  backend: model_map
  backends:
    model_map:
      default: any
      options:
        - name: glm-low
          provider: og
          model: glm-5.3-flash
          reasoning_effort: low
        - name: haiku
          provider: anthropic
          model: claude-haiku-5-5
        - name: any
          model: kimi-k3.1-pro
          reasoning_effort: high
"""


def dag_homes(case: unittest.TestCase, config: str | None):
    """Fresh homes with a two-node dag run defined under ``config`` (``None``: no config, the `default` backend)."""
    from _delegation_state import homes
    from test_dag_tool import call, node, slots_table

    stack = contextlib.ExitStack()
    case.addCleanup(stack.close)
    home = stack.enter_context(homes())
    slots_table(home)
    if config is not None:
        (home.hermes / "config.yaml").write_text(config, encoding="utf-8")
    nodes = [node("api", scope=("a.py",)), node("deep-one", category="deep", scope=("b.py",))]
    return home, call, call(action="define", run="feat", nodes=nodes)


class DagCallsPerBackendTest(unittest.TestCase):
    """`omh_dag ready` hands out calls the active Hermes backend can run."""

    def _dag(self, config: str | None):
        return dag_homes(self, config)

    @staticmethod
    def _by_category(result: dict) -> dict[str, dict]:
        return {row["category"]: row for row in result["calls"]}

    def test_default_backend_keeps_route_tool_calls(self):
        _home, _call, result = self._dag(None)
        quick = self._by_category(result)["quick"]
        self.assertEqual(quick["route"], {"tool": "omh_delegate_route", "action": "set", "category": "quick"})
        self.assertNotIn("option", quick["tasks"][0])

    def test_model_map_puts_options_on_tasks_and_retry_takes_the_next(self):
        home, call, result = self._dag(DAG_CONFIG)
        calls = self._by_category(result)
        self.assertEqual(calls["quick"]["route"],
                         {"backend": "model_map", "category": "quick", "status": "option_selected", "option": "glm-low"})
        self.assertEqual(calls["quick"]["tasks"][0]["option"], "glm-low")
        self.assertNotIn("tool", calls["quick"]["route"])
        self.assertIn("do not call omh_delegate_route", result["say"])
        # deep's chain: opus/sol have no option, kimi@high is `any`.
        self.assertEqual(calls["deep"]["tasks"][0]["option"], "any")
        retried = call(action="settle", run="feat", node="api", outcome="failed", provider_error=True)
        again = self._by_category(retried)["quick"]
        self.assertEqual((again["route"]["option"], again["tasks"][0]["option"]), ("haiku", "haiku"))
        from test_dag_run_rules import record_of

        attempts = {row["id"]: row["attempts"] for row in record_of(home)["nodes"]}["api"]
        self.assertEqual([(item["backend"], item["option"]) for item in attempts],
                         [("model_map", "glm-low"), ("model_map", "haiku")])

    def test_model_map_category_without_option_carries_none(self):
        _home, _call, result = self._dag(DAG_CONFIG.replace("model: kimi-k3.1-pro", "model: other"))
        deep = self._by_category(result)["deep"]
        self.assertEqual(deep["route"]["status"], "no_matching_option")
        self.assertNotIn("option", deep["tasks"][0])
        self.assertIn("No option of the user's runs deep", result["say"])

    def test_profile_routes_gets_no_profile(self):
        _home, _call, result = self._dag(PROFILE_ROUTES_CONFIG)
        for row in result["calls"]:
            self.assertEqual(row["route"]["status"], "not_applied")
            self.assertTrue(all(set(task) == {"goal", "context"} for task in row["tasks"]))
        self.assertIn("profile_routes backend", result["say"])

    def _identity_doc(self, home, chains: dict) -> None:
        routing = home.omh / "routing"
        routing.mkdir(parents=True, exist_ok=True)
        (routing / "identities.json").write_text(
            json.dumps({"schema_version": "omh_identity_profiles/v1", "identities": chains}),
            encoding="utf-8",
        )

    def test_model_map_identity_chain_selects_and_retries_within_it(self):
        from test_dag_tool import node

        home, call, _defined = self._dag(DAG_CONFIG)
        self._identity_doc(home, {
            "qa": {"prompt": "p", "model_chain": [
                {"model_id": "glm-5.3-flash", "reasoning_effort": "low"},
                {"model_id": "claude-haiku-5-5", "reasoning_effort": ""},
            ]},
        })
        defined = call(action="define", run="feat2", nodes=[
            {**node("a2", scope=("a2.py",)), "identity": "custom:qa"},
            node("b2", scope=("b2.py",)),
        ])
        calls = {tuple(row["nodes"]): row for row in defined["calls"]}
        identity_call = calls[("a2",)]
        # The identity's own chain picks the option: its position, not the
        # category's or another node's.
        self.assertEqual(identity_call["route"],
                         {"backend": "model_map", "category": "quick", "identity": "custom:qa",
                          "attempt": 0, "status": "option_selected", "option": "glm-low"})
        self.assertEqual(identity_call["tasks"][0]["option"], "glm-low")
        retried = call(action="settle", run="feat2", node="a2", outcome="failed", provider_error=True)
        (retry_call,) = retried["calls"]
        self.assertEqual((retry_call["route"]["attempt"], retry_call["route"]["option"],
                          retry_call["tasks"][0]["option"]), (1, "haiku", "haiku"))

    def test_identity_route_refused_when_the_backend_cannot_apply_it(self):
        from test_dag_tool import node

        for config in (PROFILE_ROUTES_CONFIG, "delegation:\n  backend: someone-elses\n"):
            with self.subTest(config=config.splitlines()[-1]):
                home, call, _defined = self._dag(config)
                result = call(action="define", run="ident", nodes=[
                    {**node("a", scope=("a.py",)), "identity": "builtin:builder"}])
                self.assertEqual((result["status"], result["reason"]),
                                 ("refused", "identity_route_unavailable"), result)
                self.assertEqual(result.get("calls", []), [])

    def test_model_map_without_a_matching_option_for_the_chain_is_refused(self):
        from test_dag_tool import node

        home, call, _defined = self._dag(DAG_CONFIG)
        self._identity_doc(home, {
            "exotic": {"prompt": "p", "model_chain": [{"model_id": "no-such-model", "reasoning_effort": "x"}]},
        })
        result = call(action="define", run="ident", nodes=[
            {**node("a", scope=("a.py",)), "identity": "custom:exotic"}])
        # No model_map option serves the chain entry: a typed refusal, never a
        # category default or another option standing in.
        self.assertEqual((result["status"], result["reason"]),
                         ("refused", "identity_route_unavailable"), result)

    def test_a_local_nodes_identity_chain_offers_only_local_options(self):
        from test_dag_tool import node

        local_map = """\
delegation:
  backend: model_map
  backends:
    model_map:
      default: any
      options:
        - name: local-llm
          provider: llamacpp
          model: local-model
        - name: cloud-fast
          provider: og
          model: glm-5.3-flash
          reasoning_effort: low
"""
        home, call, _defined = self._dag(local_map)
        self._identity_doc(home, {
            "qa": {"prompt": "p", "model_chain": [
                {"model_id": "glm-5.3-flash", "reasoning_effort": "low"},
                {"model_id": "local-model", "reasoning_effort": ""},
            ]},
        })
        defined = call(action="define", run="feat2", nodes=[
            {**node("a2", scope=("a2.py",)), "local": True, "identity": "custom:qa"}])
        (row,) = defined["calls"]
        # The cloud chain entry is not a local substitute: the local option the
        # chain's other entry maps to is handed out instead.
        self.assertEqual(row["route"]["option"], "local-llm")
        self.assertEqual(row["route"]["local"], True)
        self.assertEqual(row["tasks"][0]["option"], "local-llm")
        retried = call(action="settle", run="feat2", node="a2", outcome="failed", provider_error=True)
        # Position 1 is the cloud entry: no local option serves it, so the node
        # is held — never a cloud model stand-in.
        self.assertEqual(retried.get("calls", []), [])
        self.assertEqual(retried["held_for_local_model"], ["a2"])


OBSERVED = {"backend": "model_map", "label": "haiku", "provider": "anthropic", "model": "claude-haiku-5-5",
            "reasoning_effort": "", "service_tier": None, "fallback_activated": False}


class ObservedRouteTest(unittest.TestCase):
    """The `route` Hermes reports on a child's result is what the ledger, graph and HUD show."""

    def _sync(self, home, routes: list[dict | None]) -> None:
        from _delegation_state import PARENT, start

        from omh.plugin_bundle.omh.delegation_ledger import observe_delegate_call

        for index in range(len(routes)):
            start(home, f"child-{index}", f"sa-{index}-x", "goal", now=1_800_000_000.0 + index)
        results = [{"task_index": index, "status": "completed", **({"route": route} if route else {})}
                   for index, route in enumerate(routes)]
        self.assertTrue(observe_delegate_call(
            {"tool_name": "delegate_task", "result": json.dumps({"results": results}), "session_id": PARENT,
             "tool_call_id": "sync-1", "turn_id": "turn-3", "duration_ms": 5_000, **home.hooks()},
            now=1_800_000_003.0,
        ))

    def test_sync_result_route_lands_on_the_child_bounded(self):
        from _delegation_state import PARENT, homes

        from omh.plugin_bundle.omh.delegation_ledger import read_ledger

        with homes() as home:
            self._sync(home, [OBSERVED, None, {"backend": "", "model": "x"}])
            children = read_ledger(home.omh, PARENT)["children"]
        self.assertEqual(children[0]["observed_route"],
                         {"backend": "model_map", "label": "haiku", "provider": "anthropic",
                          "model": "claude-haiku-5-5"})
        self.assertNotIn("observed_route", children[1])
        self.assertNotIn("observed_route", children[2])  # no backend: not a backend route

    def test_graph_names_the_option_and_never_calls_it_inherit(self):
        from _delegation_state import PARENT, homes

        from omh.plugin_bundle.omh.delegation_graph import build_delegation_graph

        with homes() as home:
            home.session(PARENT, "claude-haiku-5-5")
            self._sync(home, [OBSERVED])
            home.session("child-0", "claude-haiku-5-5", parent=PARENT)
            graph = build_delegation_graph(home.omh, home.hermes, PARENT, now=1_800_000_004.0, linger=None)
        lane = next(node for node in graph["nodes"] if node["kind"] == "lane")
        self.assertEqual((lane["category"], lane["category_source"]), ("?", "backend_route"))
        self.assertEqual((lane["route_backend"], lane["route_label"]), ("model_map", "haiku"))

    def test_background_result_json_route_is_read(self):
        from _delegation_state import PARENT, dispatched, homes, start

        from omh.plugin_bundle.omh.delegation_graph import state_facts

        with homes() as home:
            home.execute("ALTER TABLE async_delegations ADD COLUMN result_json TEXT")
            home.delegation("deleg-1", ["g"])
            home.execute("UPDATE async_delegations SET result_json = ? WHERE delegation_id = 'deleg-1'",
                         (json.dumps({"task_index": 0, "status": "completed", "route": OBSERVED}),))
            start(home, "child-0", "sa-0-x", "g", now=1_800_000_000.0)
            dispatched(home, ["sa-0-x"], now=1_800_000_001.0)
            facts = state_facts(home.hermes, [PARENT, "child-0"], ["deleg-1"])
        self.assertEqual(facts["delegations"]["deleg-1"]["routes"][0]["label"], "haiku")

    def test_dag_lane_keeps_its_category_only_when_hermes_ran_the_option_handed_out(self):
        from _delegation_state import PARENT, start

        from omh.plugin_bundle.omh.delegation_graph import build_delegation_graph
        from omh.plugin_bundle.omh.delegation_ledger import observe_delegate_call

        for ran, expected in (("glm-low", ("quick", "backend_option")), ("haiku", ("?", "route_option_mismatch"))):
            with self.subTest(ran=ran):
                home, _call, _result = dag_homes(self, DAG_CONFIG)
                home.session(PARENT, "claude-opus-5-5")
                start(home, "child-api", "sa-api", "api [dag:feat/api]", now=1_800_000_000.0)
                home.session("child-api", "glm-5.3-flash", parent=PARENT)
                route = {**OBSERVED, "label": ran, "model": "glm-5.3-flash"}
                observe_delegate_call(
                    {"tool_name": "delegate_task", "session_id": PARENT, "tool_call_id": "sync-1",
                     "result": json.dumps({"results": [{"task_index": 0, "status": "completed", "route": route}]}),
                     "turn_id": "turn-3", "duration_ms": 5_000, **home.hooks()},
                    now=1_800_000_003.0,
                )
                graph = build_delegation_graph(home.omh, home.hermes, PARENT, now=1_800_000_004.0, linger=None)
                lane = next(node for node in graph["nodes"] if node.get("dag_node") == "api")
                self.assertEqual((lane["category"], lane["category_source"]), expected)
                self.assertEqual(lane["route_label"], ran)

    def test_hud_row_names_the_option(self):
        from test_tui_panels import THEME, agent_row, hud_payload, lines_text, with_agents

        from omh.tui.panels import panel_lines

        payload = with_agents(hud_payload(), [
            agent_row(0, category="", model="claude-haiku-5-5", effort="", route_label="haiku"),
            agent_row(1, category="inherit", model="claude-opus-5-5", effort="high", route_label="big"),
        ])
        body = "\n".join(lines_text(panel_lines(payload, 160, 20, THEME, 0.0)))
        self.assertIn("category:@haiku(claude-haiku-5-5)", body)
        self.assertIn("category:@big(claude-opus-5-5:high)", body)
        self.assertNotIn("inherit(", body)


if __name__ == "__main__":
    unittest.main()
