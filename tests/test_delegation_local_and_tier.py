"""What OMH learned from Hermes' model routes: a local-only dag node and the speed tier of an option.

Hermes' official `advanced-delegation` plugin documents a `local` model route
(a `base_url` on this machine) and a per-route `service_tier`
(normal / fast / ultrafast). OMH reads both from the user's `model_map`
options, read-only:

* a dag node marked ``local`` runs only on a local option, and is held --
  never sent to a cloud model -- when none is set up or every one failed;
* in the parallel and small-task categories (`swarm`, `quick`,
  `simple-work`) a fast option of a chain model is tried before the same
  model's normal option, and everywhere else the normal one leads.
"""

import contextlib
import unittest

from _local_package import load_local_package

load_local_package()

from omh.plugin_bundle.omh import dag_run  # noqa: E402
from omh.plugin_bundle.omh.delegation_backend_mode import (  # noqa: E402
    FAST_TIER_CATEGORIES,
    category_local_options,
    category_options,
    is_local_option,
    option_chain,
    read_backend_mode,
)

LOCAL_CONFIG = """\
delegation:
  backend: model_map
  backends:
    model_map:
      default: cloud
      options:
        - name: cloud
          provider: og
          model: glm-5.3-flash
          reasoning_effort: low
        - name: lan
          base_url: http://192.168.0.20:8000/v1
          model: qwen-local
        - name: studio
          provider: lmstudio
          model: gemma-local
"""

CLOUD_ONLY_CONFIG = """\
delegation:
  backend: model_map
  backends:
    model_map:
      options:
        - name: cloud
          provider: og
          model: glm-5.3-flash
          reasoning_effort: low
"""

TIER_CONFIG = """\
delegation:
  backend: model_map
  backends:
    model_map:
      options:
        - name: flash
          provider: og
          model: glm-5.3-flash
          reasoning_effort: low
        - name: flash-fast
          provider: og
          model: glm-5.3-flash
          reasoning_effort: low
          service_tier: fast
"""


def option(**fields: str) -> dict[str, str]:
    return {"name": "x", "provider": "", "model": "m", "reasoning_effort": "", "base_url": "", "service_tier": "",
            **fields}


class LocalOptionTest(unittest.TestCase):
    def test_hosts_hermes_treats_as_local_are_local(self):
        for url in ("http://localhost:11434/v1", "http://127.0.0.1:8080", "http://[::1]:8000/v1",
                    "http://192.168.1.5:8000/v1", "http://10.0.0.7/v1", "http://172.20.1.1:9000",
                    "http://100.101.2.3:8000", "http://ollama:11434/v1", "http://gpu-box.local:8000",
                    "http://host.docker.internal:8000/v1"):
            with self.subTest(url=url):
                self.assertTrue(is_local_option(option(base_url=url)))

    def test_cloud_hosts_and_cloud_providers_are_not(self):
        for fields in ({"base_url": "https://api.openai.com/v1"}, {"base_url": "https://openrouter.ai/api/v1"},
                       {"base_url": "http://8.8.8.8/v1"}, {"provider": "openrouter"}, {"provider": "anthropic"},
                       {"provider": "ollama-cloud"}, {}):
            with self.subTest(fields=fields):
                self.assertFalse(is_local_option(option(**fields)))

    def test_providers_hermes_runs_locally_are_local_without_a_base_url(self):
        for provider in ("lmstudio", "LM-Studio", "llamacpp", "llama.cpp"):
            with self.subTest(provider=provider):
                self.assertTrue(is_local_option(option(provider=provider)))

    def test_a_base_url_outranks_the_provider(self):
        # A provider Hermes serves locally, pointed at a cloud host, is not local.
        self.assertFalse(is_local_option(option(provider="lmstudio", base_url="https://api.example.com/v1")))


class CategoryLocalOptionsTest(unittest.TestCase):
    def mode(self, text: str) -> dict:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "config.yaml").write_text(text, encoding="utf-8")
            return read_backend_mode(directory)

    def test_only_local_options_in_user_order(self):
        chains = {"quick": (("glm-5.3-flash", "low"),), "deep": (("claude-opus-5-5", "high"),)}
        local = category_local_options(self.mode(LOCAL_CONFIG), chains)
        self.assertEqual(local, {"quick": ["lan", "studio"], "deep": ["lan", "studio"]})
        # The cloud option still serves the ordinary lane.
        self.assertEqual(category_options(self.mode(LOCAL_CONFIG), chains)["quick"], ["cloud"])

    def test_a_chain_model_served_locally_leads(self):
        chains = {"quick": (("gemma-local", "low"),)}
        self.assertEqual(category_local_options(self.mode(LOCAL_CONFIG), chains)["quick"], ["studio", "lan"])

    def test_no_local_option_or_another_backend_gives_none(self):
        chains = {"quick": (("glm-5.3-flash", "low"),)}
        self.assertEqual(category_local_options(self.mode(CLOUD_ONLY_CONFIG), chains), {"quick": []})
        self.assertEqual(category_local_options({"backend": "default", "status": "read"}, chains), {})
        self.assertEqual(category_local_options({"backend": "model_map", "status": "unreadable"}, chains), {})


class SpeedTierTest(unittest.TestCase):
    OPTIONS = [option(name="flash", model="glm-5.3-flash"),
               option(name="flash-fast", model="glm-5.3-flash", service_tier="fast"),
               option(name="opus", model="claude-opus-5-5")]

    def test_the_tier_categories_are_the_parallel_and_small_ones(self):
        self.assertEqual(FAST_TIER_CATEGORIES, frozenset({"swarm", "quick", "simple-work"}))
        self.assertTrue(FAST_TIER_CATEGORIES <= set(dag_run.CATEGORIES))

    def test_fast_leads_where_preferred_and_the_other_tier_follows(self):
        chain = (("glm-5.3-flash", "low"), ("claude-opus-5-5", "low"))
        fast = [entry["option"] for entry in option_chain(chain, self.OPTIONS, prefer_fast=True)]
        normal = [entry["option"] for entry in option_chain(chain, self.OPTIONS)]
        self.assertEqual(fast, ["flash-fast", "flash", "opus"])
        self.assertEqual(normal, ["flash", "flash-fast", "opus"])

    def test_every_fast_word_counts(self):
        for word in ("fast", "priority", "ultrafast", " Fast "):
            with self.subTest(word=word):
                options = [option(name="a", model="m"), option(name="b", model="m", service_tier=word)]
                chain = (("m", ""),)
                self.assertEqual(option_chain(chain, options, prefer_fast=True)[0]["option"], "b")

    def test_the_reader_carries_the_tier_and_the_category_picks_it(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "config.yaml").write_text(TIER_CONFIG, encoding="utf-8")
            mode = read_backend_mode(directory)
        self.assertEqual(mode["options"][1]["service_tier"], "fast")
        chains = {"quick": (("glm-5.3-flash", "low"),), "unspecified-low": (("glm-5.3-flash", "low"),)}
        options = category_options(mode, chains)
        self.assertEqual(options["quick"], ["flash-fast", "flash"])
        self.assertEqual(options["unspecified-low"], ["flash", "flash-fast"])


class LocalDagNodeTest(unittest.TestCase):
    """`omh_dag` never hands a local node to a model that is not local."""

    def run_dag(self, config: str | None, nodes: list[dict]):
        from _delegation_state import homes
        from test_dag_tool import call, slots_table

        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        home = stack.enter_context(homes())
        slots_table(home)
        if config is not None:
            (home.hermes / "config.yaml").write_text(config, encoding="utf-8")
        return home, call, call(action="define", run="feat", nodes=nodes)

    @staticmethod
    def nodes(local: bool = True) -> list[dict]:
        from test_dag_tool import node

        secret = node("secret", scope=("data.py",))
        secret["local"] = local
        return [node("api", scope=("a.py",)), secret]

    def test_a_local_node_takes_a_local_option_and_retry_takes_the_next_local_one(self):
        _home, call, result = self.run_dag(LOCAL_CONFIG, self.nodes())
        by_node = {node_id: row for row in result["calls"] for node_id in row["nodes"]}
        self.assertEqual(by_node["api"]["tasks"][0]["option"], "cloud")
        self.assertEqual(by_node["secret"]["tasks"][0]["option"], "lan")
        self.assertTrue(by_node["secret"]["route"]["local"])
        self.assertNotIn("local", by_node["api"]["route"])
        retried = call(action="settle", run="feat", node="secret", outcome="failed", provider_error=True)
        self.assertEqual(retried["calls"][0]["tasks"][0]["option"], "studio")

    def test_a_local_node_whose_only_local_option_failed_is_held_not_sent_to_the_cloud(self):
        one_local = LOCAL_CONFIG.replace("        - name: studio\n          provider: lmstudio\n          model: gemma-local\n", "")
        _home, call, result = self.run_dag(one_local, self.nodes())
        by_node = {node_id: row for row in result["calls"] for node_id in row["nodes"]}
        self.assertEqual(by_node["secret"]["tasks"][0]["option"], "lan")
        held = call(action="settle", run="feat", node="secret", outcome="failed", provider_error=True)
        self.assertEqual(held["calls"], [])
        self.assertEqual(held["held_for_local_model"], ["secret"])
        self.assertIn("every local model_map option", held["say"])

    def test_a_local_node_is_held_where_no_local_model_is_set_up(self):
        for name, config in (("default backend", None), ("cloud-only model_map", CLOUD_ONLY_CONFIG)):
            with self.subTest(case=name):
                _home, _call, result = self.run_dag(config, self.nodes())
                handed = [node_id for row in result["calls"] for node_id in row["nodes"]]
                self.assertEqual(handed, ["api"])
                self.assertEqual(result["held_for_local_model"], ["secret"])
                self.assertIn("never go to a cloud model", result["say"])
                self.assertIn("base_url", result["say"])

    def test_local_false_is_an_ordinary_node_with_the_digest_it_had(self):
        from test_dag_tool import node

        plain = dag_run.new_record("p", "r", None, None, [node("a")], 0)
        marked_false = node("a")
        marked_false["local"] = False
        explicit = dag_run.new_record("p", "r", None, None, [marked_false], 0)
        self.assertEqual(plain["digest"], explicit["digest"])
        self.assertNotIn("local", explicit["nodes"][0])
        marked_true = node("a")
        marked_true["local"] = True
        self.assertNotEqual(dag_run.new_record("p", "r", None, None, [marked_true], 0)["digest"], plain["digest"])

    def test_a_bad_local_value_or_an_owner_on_a_local_node_is_refused(self):
        from test_dag_tool import node

        for value in ("true", 1, None, []):
            with self.subTest(value=value):
                raw = node("a")
                raw["local"] = value
                with self.assertRaises(dag_run.DagRefusal) as caught:
                    dag_run.new_record("p", "r", None, None, [raw], 0)
                self.assertEqual(caught.exception.reason, "invalid_local")
        owned = node("a", scope=("a.py",), owner="codex")
        owned["local"] = True
        with self.assertRaises(dag_run.DagRefusal) as caught:
            dag_run.new_record("p", "r", None, None, [owned], 0)
        self.assertEqual(caught.exception.reason, "invalid_local")


if __name__ == "__main__":
    unittest.main()
