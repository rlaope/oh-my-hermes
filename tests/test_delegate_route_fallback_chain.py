"""The opt-in in-child fallback chain in `delegation.fallback_providers` (#3124).

With `write_fallback_providers: true` in `routing/delegate-route.json` and a
Hermes that honours a fallback entry's `reasoning_effort` (hermes-agent PR
#144787), `omh_delegate_route set` writes the chain positions after the head
into `delegation.fallback_providers`, each with its own provider, wire model
and effort. The key is owned like the three scalars: captured in the
baseline, put back at turn end and on `clear` (absent stays absent), covered
by the lost-update and per-conversation guards, and never written over when
the person has their own value.

Every test passes explicit temporary homes; nothing here reads or writes the
developer's own `~/.hermes` or `~/.omh`. The host gate is the real
`host_support` pointed at a fake Hermes source tree.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _module_patch import patch_modules
from omh.plugin_bundle.omh import delegation_fallback_chain
from omh.plugin_bundle.omh.delegation_fallback_chain import (
    DELEGATE_ROUTE_OPTIONS_SCHEMA_VERSION,
    host_support,
    load_fallback_chain_option,
)
from omh.plugin_bundle.omh.delegation_route_restore import load_route_restore_record
from omh.plugin_bundle.omh.delegation_routing import (
    FALLBACK_CHAIN_KEY,
    decode_fallback_chain,
    encode_fallback_chain,
    read_delegation_route,
    read_fallback_chain_state,
    write_delegation_route,
)
from omh.plugin_bundle.omh.hermes_delegation import load_delegation_route_provenance
from omh.plugin_bundle.omh.hooks.session_hooks import on_session_end, on_session_start
from omh.plugin_bundle.omh.hooks.tool_hooks import pre_tool_call
from omh.plugin_bundle.omh.tools.delegate_route_tool import omh_delegate_route_handler
from omh.maintenance.doctor import _delegate_route_fallback_chain_check
from omh.paths import OmhPaths

BASE_CONFIG = (
    "model:\n"
    "  provider: anthropic\n"
    "providers:\n"
    "  opengateway:\n"
    "    base_url: https://gateway.example.com/v1\n"
    "delegation:\n"
    "  max_concurrent_children: 4\n"
)

CHAINS = {
    "schema_version": "mixture_chain_overrides/v1",
    "categories": {
        "deep": [
            {"model": "deep-head", "reasoning_effort": "high"},
            {"model": "deep-next", "reasoning_effort": "medium"},
            {"model": "deep-last", "reasoning_effort": "low"},
            {"model": "deep-egress", "reasoning_effort": "low"},
        ],
        "quick": [
            {"model": "quick-head", "reasoning_effort": "low"},
            {"model": "quick-next", "reasoning_effort": "minimal"},
        ],
        # One alias twice at two efforts, and a backend repeated.
        "writing": [
            {"model": "dup-a", "reasoning_effort": "high"},
            {"model": "dup-b", "reasoning_effort": "low"},
            {"model": "dup-c", "reasoning_effort": "medium"},
            {"model": "dup-b", "reasoning_effort": "high"},
        ],
        "unspecified-low": [
            {"model": "dup-a", "reasoning_effort": "high"},
            {"model": "dup-a", "reasoning_effort": "low"},
            {"model": "dup-c", "reasoning_effort": "low"},
        ],
        "unspecified-high": [
            {"model": "dup-a", "reasoning_effort": "high"},
            {"model": "unrouted", "reasoning_effort": "low"},
            {"model": "dup-c", "reasoning_effort": "low"},
        ],
    },
}

ROUTES = {
    "schema_version": "model_provider_routes/v1",
    "models": {
        "deep-head": {"provider": "anthropic", "model": "claude-head"},
        "deep-next": {"provider": "anthropic", "model": "claude-next"},
        "deep-last": {"provider": "custom:opengateway", "model": "og/last"},
        # Not a provider this person configured: the position is skipped.
        "deep-egress": {"provider": "openrouter", "model": "vendor/egress"},
        "quick-head": {"provider": "anthropic", "model": "claude-quick"},
        "quick-next": {"provider": "custom:opengateway", "model": "og/quick-next"},
        "dup-a": {"provider": "anthropic", "model": "x-a"},
        "dup-b": {"provider": "anthropic", "model": "x-b"},
        "dup-c": {"provider": "anthropic", "model": "x-c"},
    },
}

# The chain is declared in the order OMH's provider reorder leaves it
# (configured providers first), so declared and effective order agree.
DEEP_CHAIN = [
    {"model": "claude-next", "provider": "anthropic", "reasoning_effort": "medium"},
    {"model": "og/last", "provider": "custom:opengateway", "reasoning_effort": "low"},
]
DEEP_BLOCK = (
    "  fallback_providers:\n"
    "    - provider: 'anthropic'\n"
    "      model: 'claude-next'\n"
    "      reasoning_effort: 'medium'\n"
    "    - provider: 'custom:opengateway'\n"
    "      model: 'og/last'\n"
    "      reasoning_effort: 'low'\n"
)


def _fake_hermes(root: Path, *, honours_entry_effort: bool) -> Path:
    """A Hermes source tree with or without hermes-agent PR #144787's module."""
    (root / "agent").mkdir(parents=True)
    (root / "agent" / "__init__.py").write_text("", encoding="utf-8")
    if honours_entry_effort:
        (root / "agent" / "fallback_reasoning.py").write_text(
            "def resolve_fallback_reasoning(agent, entry, cfg):\n"
            "    return entry.get('reasoning_effort')\n",
            encoding="utf-8",
        )
    return root


class FallbackChainTestCase(unittest.TestCase):
    honours_entry_effort = True

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.hermes_home = root / "hermes"
        self.omh_home = root / "omh"
        self.hermes_home.mkdir()
        self.config = self.hermes_home / "config.yaml"
        self.config.write_text(BASE_CONFIG, encoding="utf-8")
        self.write_routing("model-chains.json", CHAINS)
        self.write_routing("model-providers.json", ROUTES)
        self.code_root = _fake_hermes(root / "hermes-agent", honours_entry_effort=self.honours_entry_effort)
        patcher = mock.patch.object(
            delegation_fallback_chain, "host_support", lambda: host_support(self.code_root)
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def write_routing(self, name: str, document: dict) -> None:
        path = self.omh_home / "routing" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document), encoding="utf-8")

    def opt_in(self, enabled: bool = True) -> None:
        self.write_routing(
            "delegate-route.json",
            {"schema_version": DELEGATE_ROUTE_OPTIONS_SCHEMA_VERSION, "write_fallback_providers": enabled},
        )

    def homes(self) -> dict[str, str]:
        return {"hermes_home": str(self.hermes_home), "omh_home": str(self.omh_home)}

    def call(self, session: str = "A", task: str = "A-t1", **args) -> dict:
        return json.loads(
            omh_delegate_route_handler({**self.homes(), **args}, session_id=session, task_id=task)
        )

    def end_turn(self, session: str = "A", task: str = "A-t1") -> dict:
        return on_session_end(session_id=session, task_id=task, **self.homes())

    def chain_in_file(self) -> list[dict[str, str]] | None:
        chain = read_delegation_route(self.hermes_home, with_chain=True).get(FALLBACK_CHAIN_KEY)
        return decode_fallback_chain(chain) if chain else None


class OffByDefaultTest(FallbackChainTestCase):
    def test_without_the_options_document_only_the_three_scalars_are_written(self) -> None:
        result = self.call(action="set", category="deep")

        self.assertEqual(result["status"], "routed", result)
        self.assertNotIn("in_child_fallback", result)
        self.assertNotIn("fallback_providers", self.config.read_text(encoding="utf-8"))
        self.assertEqual(
            read_delegation_route(self.hermes_home),
            {"model": "claude-head", "reasoning_effort": "high", "provider": "anthropic"},
        )

    def test_an_option_set_to_false_writes_no_chain_and_says_so(self) -> None:
        self.opt_in(False)

        result = self.call(action="set", category="deep")

        self.assertEqual(result["in_child_fallback"], {"status": "off", "options": "disabled"})
        self.assertIsNone(self.chain_in_file())

    def test_an_invalid_options_document_is_off(self) -> None:
        self.write_routing("delegate-route.json", {"schema_version": "delegate_route_options/v1",
                                                   "write_fallback_providers": "yes"})

        self.assertEqual(load_fallback_chain_option(self.omh_home)[0], False)
        result = self.call(action="set", category="deep")
        self.assertEqual(result["in_child_fallback"]["status"], "off")
        self.assertTrue(result["in_child_fallback"]["options"].startswith("invalid:"))
        self.assertIsNone(self.chain_in_file())


class OlderHermesTest(FallbackChainTestCase):
    honours_entry_effort = False

    def test_an_older_hermes_gets_the_three_scalars_and_the_reason(self) -> None:
        self.opt_in()

        result = self.call(action="set", category="deep")

        self.assertEqual(result["status"], "routed", result)
        report = result["in_child_fallback"]
        self.assertEqual(report["status"], "host_unsupported")
        self.assertEqual(report["reason"], "fallback_reasoning_missing")
        self.assertIn("#144787", report["note"])
        self.assertNotIn("fallback_providers", self.config.read_text(encoding="utf-8"))


class WrittenChainTest(FallbackChainTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.opt_in()

    def test_set_writes_the_later_positions_in_chain_order_at_their_own_effort(self) -> None:
        result = self.call(action="set", category="deep")

        self.assertEqual(result["status"], "routed", result)
        report = result["in_child_fallback"]
        self.assertEqual(report["status"], "written")
        self.assertEqual([entry["alias"] for entry in report["entries"]], ["deep-next", "deep-last"])
        self.assertEqual(
            report["skipped"],
            [{"alias": "deep-egress", "provider": "openrouter", "reason": "provider_not_configured"}],
        )
        self.assertEqual(self.chain_in_file(), DEEP_CHAIN)
        self.assertIn(DEEP_BLOCK, self.config.read_text(encoding="utf-8"))
        # The re-dispatch candidates are still reported as before.
        self.assertEqual(
            [entry["alias"] for entry in result["fallback_candidates"]], ["deep-next", "deep-last", "deep-egress"]
        )
        provenance = load_delegation_route_provenance(self.omh_home)[-1]
        self.assertEqual(provenance["fallback_through"], "deep-last")
        self.assertEqual(decode_fallback_chain(provenance["fallback_providers"]), DEEP_CHAIN)

    def test_the_turn_end_restore_puts_the_file_back_byte_for_byte(self) -> None:
        before = self.config.read_bytes()
        self.assertEqual(self.call(action="set", category="deep")["status"], "routed")
        record = load_route_restore_record(self.omh_home)
        self.assertNotIn(FALLBACK_CHAIN_KEY, record["baseline"])
        self.assertEqual(decode_fallback_chain(record["written"][FALLBACK_CHAIN_KEY]), DEEP_CHAIN)

        ended = self.end_turn()

        self.assertEqual(ended["route_restore"]["status"], "cleared", ended)
        self.assertEqual(self.config.read_bytes(), before)

    def test_clear_puts_the_file_back_byte_for_byte(self) -> None:
        before = self.config.read_bytes()
        self.assertEqual(self.call(action="set", category="deep")["status"], "routed")

        self.assertEqual(self.call(action="clear")["status"], "cleared")

        self.assertEqual(self.config.read_bytes(), before)

    def test_a_second_lane_replaces_the_chain_omh_wrote(self) -> None:
        self.assertEqual(self.call(action="set", category="deep")["status"], "routed")

        result = self.call(action="set", category="quick")

        self.assertEqual(result["in_child_fallback"]["status"], "written")
        self.assertEqual(
            self.chain_in_file(),
            [{"model": "og/quick-next", "provider": "custom:opengateway", "reasoning_effort": "minimal"}],
        )
        self.assertEqual(result["route_restore"], "baseline_retained")

    def test_a_lane_with_nothing_after_its_head_takes_the_earlier_chain_out(self) -> None:
        self.assertEqual(self.call(action="set", category="deep")["status"], "routed")

        result = self.call(action="set", category="deep", attempt=2)

        self.assertEqual(result["status"], "routed", result)
        self.assertEqual(result["in_child_fallback"]["status"], "no_positions")
        self.assertEqual([entry["alias"] for entry in result["in_child_fallback"]["skipped"]], ["deep-egress"])
        self.assertIsNone(self.chain_in_file())

    def test_an_explicit_model_gets_no_chain(self) -> None:
        result = self.call(action="set", category="deep", model="claude-head", provider="anthropic")

        self.assertEqual(result["in_child_fallback"]["status"], "no_positions")
        self.assertIsNone(self.chain_in_file())

    def test_turning_the_option_off_takes_omhs_chain_out_on_the_next_set(self) -> None:
        self.assertEqual(self.call(action="set", category="deep")["status"], "routed")
        self.opt_in(False)

        self.call(action="set", category="quick")

        self.assertIsNone(self.chain_in_file())


class PersonOwnedChainTest(FallbackChainTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.opt_in()

    def assert_kept(self, config: str) -> None:
        self.config.write_text(config, encoding="utf-8")
        before = self.config.read_bytes()

        result = self.call(action="set", category="deep")

        self.assertEqual(result["status"], "routed", result)
        self.assertEqual(result["in_child_fallback"]["status"], "person_owned")
        self.assertIn("never overwrites", result["in_child_fallback"]["note"])
        route = read_delegation_route(self.hermes_home, with_chain=True)
        self.assertEqual(route["model"], "claude-head")
        text = self.config.read_text(encoding="utf-8")
        self.assertNotIn("og/last", text)
        self.assertEqual(self.end_turn()["route_restore"]["status"], "cleared")
        self.assertEqual(self.config.read_bytes(), before)

    def test_an_explicit_empty_list_is_the_persons(self) -> None:
        self.assert_kept(BASE_CONFIG + "  fallback_providers: []\n")
        self.assertEqual(read_fallback_chain_state(self.hermes_home), "foreign")

    def test_a_chain_with_keys_omh_never_writes_is_the_persons(self) -> None:
        self.assert_kept(
            BASE_CONFIG
            + "  fallback_providers:\n"
            "    - provider: custom\n"
            "      model: local-model\n"
            "      base_url: http://127.0.0.1:8080/v1\n"
        )

    def test_a_chain_in_omhs_own_shape_that_omh_did_not_write_is_the_persons(self) -> None:
        config = BASE_CONFIG + "  fallback_providers:\n    - provider: anthropic\n      model: mine\n"
        self.config.write_text(config, encoding="utf-8")
        before = self.config.read_bytes()

        result = self.call(action="set", category="deep")

        self.assertEqual(result["in_child_fallback"]["status"], "person_owned")
        self.assertEqual(self.chain_in_file(), [{"model": "mine", "provider": "anthropic"}])
        # Provenance never claims a chain the person owns.
        provenance = load_delegation_route_provenance(self.omh_home)[-1]
        self.assertNotIn("fallback_providers", provenance)
        # A second lane still does not take it: the record shows it was kept.
        self.assertEqual(self.call(action="set", category="quick")["in_child_fallback"]["status"], "person_owned")
        self.assertEqual(self.call(action="clear")["status"], "cleared")
        self.assertEqual(self.config.read_bytes(), before)

    def test_a_null_value_is_hermes_absent_and_may_be_replaced(self) -> None:
        self.config.write_text(BASE_CONFIG + "  fallback_providers: null\n", encoding="utf-8")

        result = self.call(action="set", category="deep")

        self.assertEqual(result["in_child_fallback"]["status"], "written")
        self.assertEqual(self.chain_in_file(), DEEP_CHAIN)


PERSON_CHAIN = "  fallback_providers:\n    - provider: 'anthropic'\n      model: 'my-own'\n"


class PersonChainWithTheOptionOffTest(FallbackChainTestCase):
    """A person's chain in OMH's own shape is never part of OMH's route, opted in or not."""

    def setUp(self) -> None:
        super().setUp()
        self.config.write_text(BASE_CONFIG + PERSON_CHAIN, encoding="utf-8")
        self.before = self.config.read_text(encoding="utf-8")

    def test_the_record_names_no_chain_it_did_not_write(self) -> None:
        self.assertEqual(self.call(action="set", category="deep")["status"], "routed")

        record = load_route_restore_record(self.omh_home)
        self.assertNotIn(FALLBACK_CHAIN_KEY, record["written"])
        self.assertNotIn(FALLBACK_CHAIN_KEY, record["baseline"])
        self.assertEqual(self.end_turn()["route_restore"]["status"], "cleared")
        self.assertEqual(self.config.read_text(encoding="utf-8"), self.before)

    def test_removing_their_chain_mid_turn_still_lets_the_route_come_back_out(self) -> None:
        self.assertEqual(self.call(action="set", category="deep")["status"], "routed")
        self.config.write_text(self.config.read_text(encoding="utf-8").replace(PERSON_CHAIN, ""), encoding="utf-8")

        ended = self.end_turn()

        self.assertEqual(ended["route_restore"]["status"], "cleared", ended)
        self.assertEqual(self.config.read_text(encoding="utf-8"), BASE_CONFIG)

    def test_a_lost_record_does_not_turn_their_chain_into_omhs(self) -> None:
        self.assertEqual(self.call(action="set", category="deep")["status"], "routed")
        (self.omh_home / "routing" / "route-restore.json").unlink()
        # The next route finds OMH's leftover scalars and the person's chain.
        self.assertEqual(self.call(task="A-t2", action="set", category="quick")["status"], "routed")
        self.assertEqual(self.end_turn(task="A-t2")["route_restore"]["status"], "cleared")
        self.assertEqual(self.config.read_text(encoding="utf-8"), self.before)
        # Opted in, the same history still leaves their chain alone.
        self.opt_in()
        self.assertEqual(self.call(task="A-t3", action="set", category="deep")["in_child_fallback"]["status"],
                         "person_owned")
        self.assertIn(PERSON_CHAIN, self.config.read_text(encoding="utf-8"))

    def test_a_dispatch_never_writes_their_removed_chain_back(self) -> None:
        self.assertEqual(self.call(action="set", category="deep")["status"], "routed")
        self.config.write_text(self.config.read_text(encoding="utf-8").replace(PERSON_CHAIN, ""), encoding="utf-8")

        directive = pre_tool_call(
            tool_name="delegate_task", args={"goal": "lane"}, session_id="A", task_id="A-t1",
            tool_call_id="A-call", turn_id="A-turn", **self.homes(),
        )

        self.assertIsNone(directive)
        self.assertNotIn("fallback_providers", self.config.read_text(encoding="utf-8"))
        self.assertEqual(read_delegation_route(self.hermes_home)["model"], "claude-head")


class TwoDelegationSectionsTest(FallbackChainTestCase):
    def test_a_file_with_two_sections_gets_no_chain_and_no_person_owned_claim(self) -> None:
        # The route guard already refuses such a file for a route; the block
        # writer keeps out of it on its own too, and says why.
        self.config.write_text(BASE_CONFIG + "other: 1\ndelegation:\n  max_iterations: 3\n", encoding="utf-8")
        chain = encode_fallback_chain(DEEP_CHAIN)

        result = write_delegation_route(self.hermes_home, model="m", fallback_providers=chain)

        self.assertEqual(result["fallback_chain"], "kept_unsupported_config")
        self.assertEqual(read_fallback_chain_state(self.hermes_home), "unsupported")
        self.assertNotIn("fallback_providers", self.config.read_text(encoding="utf-8"))


class GuardsTest(FallbackChainTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.opt_in()

    def test_a_person_editing_omhs_chain_keeps_their_chain_and_gets_the_scalars_back_out(self) -> None:
        self.assertEqual(self.call(action="set", category="deep")["status"], "routed")
        edited = self.config.read_text(encoding="utf-8").replace("'og/last'", "'my-own-last'")
        self.config.write_text(edited, encoding="utf-8")

        ended = self.end_turn()

        self.assertEqual(ended["route_restore"]["status"], "chain_foreign_edit", ended)
        self.assertEqual(read_delegation_route(self.hermes_home), {})
        self.assertIn("'my-own-last'", self.config.read_text(encoding="utf-8"))
        self.assertIsNone(load_route_restore_record(self.omh_home) or None)

    def test_a_person_removing_omhs_chain_mid_turn_still_gets_the_scalars_back_out(self) -> None:
        self.assertEqual(self.call(action="set", category="deep")["status"], "routed")
        self.config.write_text(self.config.read_text(encoding="utf-8").replace(DEEP_BLOCK, ""), encoding="utf-8")

        ended = self.end_turn()

        self.assertEqual(ended["route_restore"]["status"], "chain_foreign_edit", ended)
        self.assertEqual(self.config.read_text(encoding="utf-8"), BASE_CONFIG)

    def test_the_option_turned_off_is_not_undone_by_a_later_dispatch(self) -> None:
        # A routes with the chain, the person turns the option off, B's set
        # takes OMH's chain out; A's next dispatch must not write it back.
        self.assertEqual(self.call("A", "A-t1", action="set", category="deep")["status"], "routed")
        self.opt_in(False)
        self.assertEqual(self.call("B", "B-t1", action="set", category="quick")["status"], "routed")
        self.assertIsNone(self.chain_in_file())

        directive = pre_tool_call(
            tool_name="delegate_task", args={"goal": "lane"}, session_id="A", task_id="A-t1",
            tool_call_id="A-call", turn_id="A-turn", **self.homes(),
        )

        self.assertIsNone(directive)
        self.assertEqual(read_delegation_route(self.hermes_home)["model"], "claude-head")
        self.assertIsNone(self.chain_in_file())

    def test_turning_the_option_off_while_a_route_is_live_still_restores_it(self) -> None:
        self.assertEqual(self.call(action="set", category="deep")["status"], "routed")
        self.opt_in(False)

        self.assertEqual(self.end_turn()["route_restore"]["status"], "cleared")
        self.assertEqual(self.config.read_text(encoding="utf-8"), BASE_CONFIG)

    def test_a_session_start_restore_takes_a_killed_sessions_chain_out(self) -> None:
        self.assertEqual(self.call("killed", "killed-t1", action="set", category="deep")["status"], "routed")
        path = self.omh_home / "routing" / "route-restore.json"
        record = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn(FALLBACK_CHAIN_KEY, record["written"])
        path.write_text(json.dumps({**record, "written_at": 0.0, "baseline_captured_at": 0.0}), encoding="utf-8")

        started = on_session_start(session_id="fresh", **self.homes())

        self.assertEqual(started["route_restore"]["status"], "cleared", started)
        self.assertEqual(self.config.read_text(encoding="utf-8"), BASE_CONFIG)

    def test_another_sessions_route_is_replaced_by_this_conversations_chain_at_dispatch(self) -> None:
        self.assertEqual(self.call("A", "A-t1", action="set", category="deep")["status"], "routed")
        self.assertEqual(self.call("B", "B-t1", action="set", category="quick")["status"], "routed")
        self.assertEqual(self.chain_in_file()[0]["model"], "og/quick-next")

        directive = pre_tool_call(
            tool_name="delegate_task",
            args={"goal": "lane"},
            session_id="A",
            task_id="A-t1",
            tool_call_id="A-call",
            turn_id="A-turn",
            **self.homes(),
        )

        self.assertIsNone(directive)
        self.assertEqual(read_delegation_route(self.hermes_home)["model"], "claude-head")
        self.assertEqual(self.chain_in_file(), DEEP_CHAIN)

    def test_a_chain_changed_between_read_and_write_refuses_the_fallback(self) -> None:
        self.assertEqual(self.call(action="set", category="deep")["status"], "routed")
        route = read_delegation_route(self.hermes_home, with_chain=True)
        changed = dict(route, fallback_providers=encode_fallback_chain([{"provider": "anthropic", "model": "x"}]))

        result = write_delegation_route(
            self.hermes_home, model="claude-last", provider="anthropic", fallback_providers="",
            expected_previous=changed,
        )

        self.assertEqual(result["status"], "error")
        self.assertEqual(self.chain_in_file(), DEEP_CHAIN)


class WhatHermesWillTryTest(FallbackChainTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.opt_in()

    def test_writing_stops_at_a_backend_an_earlier_entry_already_has(self) -> None:
        result = self.call(action="set", category="writing")

        report = result["in_child_fallback"]
        self.assertEqual([(entry["alias"], entry["position"]) for entry in report["entries"]],
                         [("dup-b", 1), ("dup-c", 2)])
        self.assertEqual(report["skipped"],
                         [{"alias": "dup-b", "provider": "anthropic", "reason": "same_backend_as_earlier"}])
        provenance = load_delegation_route_provenance(self.omh_home)[-1]
        self.assertEqual((provenance["fallback_through"], provenance["fallback_through_index"]), ("dup-c", "2"))

    def test_a_position_on_the_heads_own_backend_is_not_written(self) -> None:
        result = self.call(action="set", category="unspecified-low")

        self.assertEqual(result["in_child_fallback"]["status"], "no_positions")
        self.assertEqual(result["in_child_fallback"]["skipped"][0]["reason"], "same_backend_as_earlier")
        self.assertIsNone(self.chain_in_file())

    def test_a_position_with_no_provider_route_ends_the_written_chain(self) -> None:
        result = self.call(action="set", category="unspecified-high")

        self.assertEqual(result["in_child_fallback"]["status"], "no_positions")
        self.assertEqual(result["in_child_fallback"]["skipped"],
                         [{"alias": "unrouted", "provider": "", "reason": "no_provider_route"}])

    def test_fallback_goes_on_at_the_untried_repeat_of_an_alias(self) -> None:
        # writing: dup-a -> dup-b:low -> dup-c -> dup-b:high. The child walked
        # dup-b:low and dup-c; dup-b:high is the next position, not dup-b:low.
        self.assertEqual(self.call(action="set", category="writing")["status"], "routed")
        self.end_turn()

        result = self.call(task="A-t2", action="fallback")

        self.assertEqual(result["status"], "fell_back", result)
        self.assertEqual(result["walked_in_child"], ["dup-b", "dup-c"])
        self.assertEqual((result["applied"]["alias"], result["applied"]["reasoning_effort"]), ("dup-b", "high"))


class FallbackAdvancesPastTheChildsWalkTest(FallbackChainTestCase):
    def test_fallback_after_an_in_child_chain_starts_after_its_last_position(self) -> None:
        self.opt_in()
        self.assertEqual(self.call(action="set", category="deep")["status"], "routed")
        self.end_turn()

        result = self.call(task="A-t2", action="fallback")

        # deep-next and deep-last were the child's own fallbacks, so nothing
        # in the chain is left to re-dispatch to.
        self.assertEqual(result["status"], "exhausted_to_inherit", result)
        self.assertEqual(result["walked_in_child"], ["deep-next", "deep-last"])
        self.assertEqual(result["skipped_unconfigured"], [{"alias": "deep-egress", "provider": "openrouter"}])

    def test_a_route_without_a_chain_falls_back_to_the_next_position_with_its_own_chain(self) -> None:
        self.assertEqual(self.call(action="set", category="deep")["status"], "routed")
        self.end_turn()
        self.opt_in()

        result = self.call(task="A-t2", action="fallback")

        self.assertEqual(result["status"], "fell_back", result)
        self.assertEqual(result["applied"]["alias"], "deep-next")
        self.assertNotIn("walked_in_child", result)
        self.assertEqual(result["in_child_fallback"]["status"], "written")
        self.assertEqual(
            self.chain_in_file(), [{"model": "og/last", "provider": "custom:opengateway", "reasoning_effort": "low"}]
        )
        self.assertEqual(self.end_turn(task="A-t2")["route_restore"]["status"], "cleared")
        self.assertEqual(self.config.read_text(encoding="utf-8"), BASE_CONFIG)


class BlockWriterTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.hermes_home = Path(temporary.name)
        self.config = self.hermes_home / "config.yaml"
        self.config.write_text("delegation:\n  max_iterations: 5\n", encoding="utf-8")

    def test_a_value_that_could_carry_yaml_structure_is_refused(self) -> None:
        for model in ("m\n  base_url: http://evil", "m' # x", "a: b", "[x]", "{x: y}", "m #c", ""):
            with self.subTest(model=model):
                self.assertIsNone(encode_fallback_chain([{"provider": "anthropic", "model": model}]))
        forged = json.dumps([{"provider": "anthropic", "model": "m\nbase_url: x"}])
        result = write_delegation_route(self.hermes_home, model="m", fallback_providers=forged)
        self.assertEqual(result, {"status": "error", "error": "invalid fallback_providers value"})
        self.assertEqual(self.config.read_text(encoding="utf-8"), "delegation:\n  max_iterations: 5\n")

    def test_a_symlinked_config_is_refused(self) -> None:
        if not hasattr(os, "symlink"):
            self.skipTest("no symlinks")
        target = self.hermes_home / "real.yaml"
        target.write_text("delegation:\n  max_iterations: 5\n", encoding="utf-8")
        self.config.unlink()
        try:
            os.symlink(target, self.config)
        except OSError:
            self.skipTest("symlink creation not permitted")
        chain = encode_fallback_chain([{"provider": "anthropic", "model": "m"}])

        result = write_delegation_route(self.hermes_home, model="m", fallback_providers=chain)

        self.assertEqual(result["status"], "error")
        if hasattr(os, "O_NOFOLLOW"):
            # Windows has no O_NOFOLLOW and refuses on the stamp instead.
            self.assertIn("symlink", result["error"])
        self.assertEqual(target.read_text(encoding="utf-8"), "delegation:\n  max_iterations: 5\n")

    def test_a_chain_hermes_re_dumped_in_pyyamls_shape_is_still_omhs(self) -> None:
        # PyYAML writes `- ` at the key's own indent and sorts the keys.
        self.config.write_text(
            "delegation:\n"
            "  fallback_providers:\n"
            "  - model: claude-next\n"
            "    provider: anthropic\n"
            "    reasoning_effort: medium\n"
            "  max_iterations: 5\n",
            encoding="utf-8",
        )

        self.assertEqual(read_fallback_chain_state(self.hermes_home), "chain")
        self.assertEqual(
            decode_fallback_chain(read_delegation_route(self.hermes_home, with_chain=True)[FALLBACK_CHAIN_KEY]), DEEP_CHAIN[:1]
        )
        result = write_delegation_route(self.hermes_home, fallback_providers="")
        self.assertEqual(result["fallback_chain"], "removed")
        self.assertEqual(self.config.read_text(encoding="utf-8"), "delegation:\n  max_iterations: 5\n")

    def test_a_bare_key_with_nothing_under_it_is_null(self) -> None:
        self.config.write_text("delegation:\n  fallback_providers:\n  max_iterations: 5\n", encoding="utf-8")
        chain = encode_fallback_chain([{"provider": "anthropic", "model": "m"}])

        self.assertEqual(read_fallback_chain_state(self.hermes_home), "absent")
        self.assertEqual(write_delegation_route(self.hermes_home, fallback_providers=chain)["fallback_chain"], "written")
        self.assertEqual(read_fallback_chain_state(self.hermes_home), "chain")

    def test_an_inline_comment_on_an_entry_makes_the_chain_the_persons(self) -> None:
        text = "delegation:\n  fallback_providers:\n    - provider: 'anthropic'  # mine\n      model: 'm'\n"
        self.config.write_text(text, encoding="utf-8")

        self.assertEqual(read_fallback_chain_state(self.hermes_home), "foreign")
        self.assertEqual(write_delegation_route(self.hermes_home, fallback_providers="")["fallback_chain"],
                         "kept_person_owned")
        self.assertEqual(self.config.read_text(encoding="utf-8"), text)

    def test_a_comment_inside_the_block_makes_it_the_persons(self) -> None:
        text = "delegation:\n  fallback_providers:\n    # mine\n    - provider: anthropic\n      model: m\n"
        self.config.write_text(text, encoding="utf-8")

        self.assertEqual(read_fallback_chain_state(self.hermes_home), "foreign")
        result = write_delegation_route(self.hermes_home, fallback_providers="")
        self.assertEqual(result["fallback_chain"], "kept_person_owned")
        self.assertEqual(self.config.read_text(encoding="utf-8"), text)

    def test_callers_that_do_not_ask_leave_the_chain_alone(self) -> None:
        text = "delegation:\n  fallback_providers:\n    - provider: anthropic\n      model: m\n"
        self.config.write_text(text, encoding="utf-8")

        result = write_delegation_route(self.hermes_home, model="x")
        self.assertNotIn("fallback_chain", result)
        self.assertEqual(
            self.config.read_text(encoding="utf-8"),
            "delegation:\n  model: 'x'\n  fallback_providers:\n    - provider: anthropic\n      model: m\n",
        )
        self.assertEqual(write_delegation_route(self.hermes_home, clear=True)["status"], "cleared")
        self.assertEqual(self.config.read_text(encoding="utf-8"), text)


class HostSupportTest(unittest.TestCase):
    def test_the_capability_is_hermes_agent_144787s_module(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self.assertEqual(host_support(root / "none")["reason"], "fallback_reasoning_missing")
            older = _fake_hermes(root / "older", honours_entry_effort=False)
            self.assertFalse(host_support(older)["supported"])
            other = _fake_hermes(root / "other", honours_entry_effort=False)
            (other / "agent" / "fallback_reasoning.py").write_text("def other():\n    pass\n", encoding="utf-8")
            self.assertEqual(host_support(other)["reason"], "fallback_reasoning_without_entry_effort")
            newer = _fake_hermes(root / "newer", honours_entry_effort=True)
            support = host_support(newer)
            self.assertTrue(support["supported"])
            self.assertTrue(support["evidence"].endswith("agent/fallback_reasoning.py"))

    def test_a_same_named_function_without_the_entry_read_is_not_the_capability(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _fake_hermes(Path(temporary), honours_entry_effort=False)
            (root / "agent" / "fallback_reasoning.py").write_text(
                "def resolve_fallback_reasoning(agent, cfg):\n    return cfg.get('reasoning_effort')\n",
                encoding="utf-8",
            )
            self.assertEqual(host_support(root)["reason"], "fallback_reasoning_without_entry_effort")

    def test_a_capability_newer_than_the_running_process_is_restart_pending(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _fake_hermes(Path(temporary), honours_entry_effort=True)
            module = root / "agent" / "fallback_reasoning.py"
            os.utime(module, (2000.0, 2000.0))
            self.assertEqual(host_support(root, started_at=1000.0)["reason"], "restart_pending")
            self.assertTrue(host_support(root, started_at=3000.0)["supported"])
            with mock.patch.object(delegation_fallback_chain, "running_hermes_code_root", return_value=root), \
                    mock.patch.object(delegation_fallback_chain, "PROCESS_LOADED_AT", 1000.0):
                self.assertEqual(host_support()["reason"], "restart_pending")

    def test_the_capability_loaded_in_this_process_is_support(self) -> None:
        loaded = mock.Mock(resolve_fallback_reasoning=lambda agent, entry, cfg: None, __file__="loaded.py")
        with patch_modules({"agent.fallback_reasoning": loaded}), \
                mock.patch.object(delegation_fallback_chain, "running_hermes_code_root", return_value=None):
            self.assertEqual(host_support()["reason"], "capability_loaded")

    def test_the_running_hermes_is_found_without_importing_it(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = _fake_hermes(Path(temporary) / "hermes-agent", honours_entry_effort=True)
            if "agent" in sys.modules:
                self.skipTest("an `agent` package is already imported in this process")
            sys.path.insert(0, str(root))
            try:
                found = delegation_fallback_chain.running_hermes_code_root()
                self.assertNotIn("agent", sys.modules)
            finally:
                sys.path.remove(str(root))
            self.assertEqual(Path(os.path.realpath(found)), Path(os.path.realpath(root)))

    def test_no_running_hermes_is_not_support(self) -> None:
        with mock.patch.object(delegation_fallback_chain, "running_hermes_code_root", return_value=None):
            self.assertEqual(
                host_support(), {"supported": False, "reason": "hermes_source_not_found", "evidence": ""}
            )


class DoctorTest(unittest.TestCase):
    """`omh doctor` says whether the chain is written and, when it is not, why."""

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        self.paths = OmhPaths(omh_home=root / "omh", hermes_home=root / "hermes")
        self.paths.hermes_home.mkdir()
        install = self.paths.hermes_home / "hermes-agent"
        (install / "hermes_cli").mkdir(parents=True)
        self.install = install
        patcher = mock.patch.dict(os.environ, {"HERMES_PYTHON": ""})
        patcher.start()
        self.addCleanup(patcher.stop)

    def opt_in(self) -> None:
        path = self.paths.omh_home / "routing" / "delegate-route.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"schema_version": DELEGATE_ROUTE_OPTIONS_SCHEMA_VERSION,
                                    "write_fallback_providers": True}), encoding="utf-8")

    def test_off_by_default_is_ok_and_names_the_opt_in(self) -> None:
        check = _delegate_route_fallback_chain_check(self.paths)
        self.assertEqual((check.ok, check.severity, check.observed), (True, "ok", False))
        self.assertIn("write_fallback_providers", check.message)

    def test_an_older_hermes_warns_and_names_why(self) -> None:
        self.opt_in()
        _fake_hermes(self.install, honours_entry_effort=False)
        check = _delegate_route_fallback_chain_check(self.paths)
        self.assertEqual((check.ok, check.severity), (True, "warning"))
        self.assertIn("#144787", check.message)
        self.assertIn("reasoning_overrides", check.message)
        self.assertIn("writes only delegation.model", check.message)

    def test_a_person_owned_key_warns(self) -> None:
        self.opt_in()
        _fake_hermes(self.install, honours_entry_effort=True)
        (self.paths.hermes_home / "config.yaml").write_text("delegation:\n  fallback_providers: []\n", encoding="utf-8")
        check = _delegate_route_fallback_chain_check(self.paths)
        self.assertEqual(check.severity, "warning")
        self.assertIn("never overwrites", check.message)

    def test_an_empty_list_is_named_as_fallback_off_and_unsetting_it_opts_in(self) -> None:
        self.opt_in()
        _fake_hermes(self.install, honours_entry_effort=True)
        (self.paths.hermes_home / "config.yaml").write_text("delegation:\n  fallback_providers: []\n", encoding="utf-8")
        check = _delegate_route_fallback_chain_check(self.paths)
        self.assertIn("turns in-child fallback off", check.message)
        self.assertIn("to opt in", check.next_action)

    def test_a_capability_newer_than_the_gateway_is_restart_pending(self) -> None:
        self.opt_in()
        _fake_hermes(self.install, honours_entry_effort=True)
        pid = self.paths.hermes_home / "gateway.pid"
        pid.write_text("1", encoding="utf-8")
        os.utime(pid, (1000.0, 1000.0))
        check = _delegate_route_fallback_chain_check(self.paths)
        self.assertEqual(check.severity, "warning")
        self.assertIn("changed after this Hermes started", check.message)
        self.assertIn("restart the Hermes gateway", check.next_action)

    def test_a_person_owned_chain_in_omhs_shape_warns(self) -> None:
        self.opt_in()
        _fake_hermes(self.install, honours_entry_effort=True)
        (self.paths.hermes_home / "config.yaml").write_text(
            "delegation:\n  fallback_providers:\n    - provider: anthropic\n      model: mine\n", encoding="utf-8"
        )
        check = _delegate_route_fallback_chain_check(self.paths)
        self.assertEqual(check.severity, "warning")
        self.assertIn("never overwrites", check.message)

    def test_a_supporting_hermes_is_ok(self) -> None:
        self.opt_in()
        _fake_hermes(self.install, honours_entry_effort=True)
        check = _delegate_route_fallback_chain_check(self.paths)
        self.assertEqual((check.ok, check.severity, check.observed), (True, "ok", True))
        self.assertIn("also writes the chain positions", check.message)


if __name__ == "__main__":
    unittest.main()
