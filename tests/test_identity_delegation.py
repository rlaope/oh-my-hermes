"""D4 — Identity metadata bound to real handoff/route payloads, task-bound.

Covers the wiring between the validated `omh_identity_profiles/v1` selection
(D1/D2) and the prompt marker (D3) and the actual delegation surfaces:

* fanout unit handoffs freeze `identity_id`/`identity_fingerprint`/selected
  model/effort/claim_boundary — never prompt text — per unit, so each task
  carries only its own declared identity;
* `coding delegate` payloads and their handoff carry the same bounded route
  when `--identity` is declared, staying byte-identical without one;
* `omh_delegate_route` resolves an `identity` arg under the default backend
  (writing the route plus a provenance record carrying `identity`/
  `identity_digest`), matches the user's `model_map` options under that
  backend, and answers typed `not_applied` under `profile_routes` and
  `choice_required` for an unknown name;
* conversation A/B isolation, repeated dispatch, route restore/clear, and
  nested explicit marker all behave exactly as they do for categories;
* a config edited between prepare and read shows up as a changed
  fingerprint/digest, not silently as the same identity.

Every test uses explicit temporary homes; nothing touches `~/.hermes` or
`~/.omh`.
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path

from _hermes_session_rows import row, write_sessions
from _local_package import load_local_package

load_local_package()

from omh.coding.fanout import build_fanout_contract
from omh.coding.fanout_contracts import FanoutContractError
from omh.coding.identity_profiles import read_identity_profiles_config
from omh.coding.model_routing import model_route_for_unit
from omh.coding.coding_delegation import build_coding_delegation_payload
from omh.coding.maestro.contracts import ExternalHandoffRequest
from omh.coding.maestro.facade import build_external_handoff
from omh.plugin_bundle.omh.delegation_route_restore import (
    load_conversation_routes,
    load_route_restore_record,
)
from omh.plugin_bundle.omh.delegation_routing import read_delegation_route
from omh.plugin_bundle.omh.hermes_delegation import (
    append_delegation_route_provenance,
    load_delegation_route_provenance,
)
from omh.plugin_bundle.omh.hooks.session_hooks import on_session_end
from omh.plugin_bundle.omh.hooks.tool_hooks import pre_tool_call
from omh.plugin_bundle.omh.omh_identities import read_identity_chains, read_identity_prompts
from omh.plugin_bundle.omh.tools.delegate_route_tool import omh_delegate_route_handler


BASE_CONFIG = (
    "model:\n"
    "  provider: test-parent\n"
    "delegation:\n"
    "  max_concurrent_children: 4\n"
)

MODEL_MAP_CONFIG = """\
delegation:
  backend: model_map
  backends:
    model_map:
      default: everyday
      options:
        - name: fast-flash
          provider: og
          model: deepseek-flash
          reasoning_effort: low
        - name: sol-high
          provider: openrouter
          model: openai/gpt-6.1-sol
          reasoning_effort: xhigh
        - name: everyday
          model: kimi-k3.1-pro
"""

PROFILE_ROUTES_CONFIG = """\
delegation:
  backend: profile_routes
  backends:
    profile_routes:
      default: coder
      profiles:
        - name: coder
        - name: researcher
"""

IDENTITIES = {
    "schema_version": "omh_identity_profiles/v1",
    "identities": {
        "script-coding": {
            "prompt": "Implement small scripts directly.",
            "model_chain": [
                {"model_id": "deepseek-flash", "reasoning_effort": "low"},
                {"model_id": "glm-5.3-flash", "reasoning_effort": "low"},
            ],
        },
        "review": {
            "prompt": "Find concrete defects first.",
            "model_chain": [
                {"model_id": "gpt-6.1-sol", "reasoning_effort": "xhigh"},
            ],
        },
    },
}

IDENTITIES_TWO_CHAINS = {
    "schema_version": "omh_identity_profiles/v1",
    "identities": {
        "alpha": {
            "prompt": "Alpha prompt.",
            "model_chain": [{"model_id": "alpha-head", "reasoning_effort": "high"}],
        },
        "beta": {
            "prompt": "Beta prompt.",
            "model_chain": [{"model_id": "beta-head", "reasoning_effort": "low"}],
        },
    },
}


class _Homes:
    def __init__(self, root: Path) -> None:
        self.omh = root / "omh"
        self.hermes = root / "hermes"
        self.omh.mkdir(parents=True)
        self.hermes.mkdir(parents=True)
        (self.hermes / "config.yaml").write_text(BASE_CONFIG, encoding="utf-8")

    def write_identities(self, document: object = IDENTITIES) -> None:
        routing = self.omh / "routing"
        routing.mkdir(parents=True, exist_ok=True)
        (routing / "identities.json").write_text(json.dumps(document), encoding="utf-8")

    def homes(self) -> dict[str, str]:
        return {"omh_home": str(self.omh), "hermes_home": str(self.hermes)}


def _fresh(tmp: tempfile.TemporaryDirectory, config: str = BASE_CONFIG) -> _Homes:
    root = Path(tmp.name)
    homes = _Homes(root)
    (homes.hermes / "config.yaml").write_text(config, encoding="utf-8")
    return homes


class BundleChainReaderTest(unittest.TestCase):
    """The plugin-bundle chain reader matches the canonical loader's contract."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.homes = _fresh(self._tmp)

    def test_absent_document_reads_empty(self):
        result = read_identity_chains(self.homes.omh)
        self.assertEqual(result["identities"], {})
        self.assertIsNone(result["fingerprint"])

    def test_valid_document_gives_chains_and_fingerprint(self):
        self.homes.write_identities()
        result = read_identity_chains(self.homes.omh)
        self.assertEqual(
            result["identities"]["script-coding"],
            (("deepseek-flash", "low"), ("glm-5.3-flash", "low")),
        )
        self.assertEqual(result["fingerprint"]["source"], "identities.json")
        self.assertTrue(result["fingerprint"]["digest"])

    def test_fingerprint_matches_canonical_loader(self):
        self.homes.write_identities()
        bundle = read_identity_chains(self.homes.omh)
        canonical = read_identity_profiles_config(self.homes.omh)
        self.assertEqual(bundle["fingerprint"], canonical["fingerprint"])

    def test_chain_invalid_profile_is_dropped(self):
        document = {
            "schema_version": "omh_identity_profiles/v1",
            "identities": {
                "good": {
                    "prompt": "ok",
                    "model_chain": [{"model_id": "m1", "reasoning_effort": "low"}],
                },
                "bad": {
                    "prompt": "ok",
                    "model_chain": [{"model_id": "-injected", "reasoning_effort": "low"}],
                },
                "jev": {
                    "prompt": "ok",
                    "model_chain": [{"model_id": "jev-1.13", "reasoning_effort": ""}],
                },
            },
        }
        self.homes.write_identities(document)
        result = read_identity_chains(self.homes.omh)
        self.assertEqual(sorted(result["identities"]), ["good"])

    def test_prompt_only_valid_profile_is_excluded(self):
        # A profile whose chain is invalid is dropped from the chain view. The
        # prompt reader drops it too (test_prompt_reader_admits_only_chain_valid_profiles).
        document = {
            "schema_version": "omh_identity_profiles/v1",
            "identities": {
                "broken-chain": {
                    "prompt": "ok",
                    "model_chain": [{"model_id": "", "reasoning_effort": ""}],
                },
            },
        }
        self.homes.write_identities(document)
        self.assertEqual(read_identity_chains(self.homes.omh)["identities"], {})

    def test_prompt_reader_admits_only_chain_valid_profiles(self):
        # One per-profile contract for both views: a profile with an invalid
        # chain or an unknown field injects no prompt either.
        document = {
            "schema_version": "omh_identity_profiles/v1",
            "identities": {
                "good": {"prompt": "ok", "model_chain": [{"model_id": "deepseek-flash", "reasoning_effort": ""}]},
                "half": {"prompt": "p", "model_chain": []},
                "extra": {"prompt": "p", "model_chain": [{"model_id": "m", "reasoning_effort": ""}], "unknown": "x"},
            },
        }
        self.homes.write_identities(document)
        self.assertEqual(read_identity_prompts(self.homes.omh), {"good": "ok"})


class FanoutIdentityContractTest(unittest.TestCase):
    """The structured `identity` unit field freezes bounded route metadata."""

    def test_identity_unit_freezes_route_with_bounded_metadata(self):
        contract = build_fanout_contract(
            "split work",
            [
                {
                    "unit_id": "impl",
                    "owner": "codex",
                    "file_scope": ["src/"],
                    "identity": "script-coding",
                },
                {"unit_id": "docs", "owner": "codex", "file_scope": ["docs/"]},
            ],
            identity_config={
                "schema_version": "omh_identity_profiles/v1",
                "identities": {
                    "script-coding": {
                        "prompt": "Implement small scripts directly.",
                        "model_chain": (
                            {"model_id": "deepseek-flash", "reasoning_effort": "low"},
                        ),
                    }
                },
                "fingerprint": {"source": "identities.json", "digest": "abcd1234abcd1234"},
            },
        )
        units = {unit["unit_id"]: unit for unit in contract["units"]}
        route = units["impl"]["handoff"]["model_route"]
        self.assertEqual(route["identity_id"], "script-coding")
        self.assertEqual(route["identity_fingerprint"]["digest"], "abcd1234abcd1234")
        self.assertEqual(route["selected_model"], "deepseek-flash")
        self.assertEqual(route["selected_reasoning_effort"], "low")
        self.assertEqual(route["catalog_kind"], "user_identity_config")
        self.assertEqual(route["provenance"], "identity_chain_head")
        self.assertIn("claim_boundary", route)
        self.assertNotIn("Implement small scripts", json.dumps(contract))
        self.assertNotIn("model_route", units["docs"]["handoff"])

    def test_identity_and_explicit_model_in_unit(self):
        route = model_route_for_unit(
            {"unit_id": "u", "identity": "script-coding", "model": "custom-model"},
            "codex",
            identity_config={
                "identities": {"script-coding": {"prompt": "p", "model_chain": ({"model_id": "deepseek-flash"},)}},
                "fingerprint": {"source": "identities.json", "digest": "d1"},
            },
        )
        assert route is not None
        self.assertEqual(route["selected_model"], "custom-model")
        self.assertEqual(route["identity_id"], "script-coding")

    def test_unknown_identity_unit_records_unknown_attempt(self):
        route = model_route_for_unit(
            {"unit_id": "u", "identity": "ghost"},
            "codex",
            identity_config={"identities": {}, "fingerprint": {"digest": "d"}},
        )
        # No matching identity means no identity route; the name lands in
        # attempted[] instead of silently falling back to another chain.
        assert route is not None
        stages = {(a["stage"], a["outcome"]) for a in route["attempted"]}
        self.assertIn(("requested_identity", "unknown"), stages)
        self.assertNotIn("identity_id", route)

    def test_malformed_identity_name_fails_freeze(self):
        with self.assertRaises(FanoutContractError):
            build_fanout_contract(
                "split",
                [{"unit_id": "u", "file_scope": ["src/"], "identity": "Bad Name!"}],
            )

    def test_no_identity_config_keeps_old_contract(self):
        units = [{"unit_id": "a", "owner": "codex", "file_scope": ["src/"]}]
        with_config = build_fanout_contract(
            "split",
            units,
            identity_config={
                "identities": {"x": {"prompt": "p", "model_chain": ({"model_id": "m"},)}},
                "fingerprint": {"digest": "d"},
            },
        )
        without_config = build_fanout_contract("split", units)
        self.assertEqual(with_config, without_config)


class CodingDelegationIdentityTest(unittest.TestCase):
    """`build_coding_delegation_payload` carries identity route metadata."""

    _IDENTITY_CONFIG = {
        "schema_version": "omh_identity_profiles/v1",
        "identities": {
            "script-coding": {
                "prompt": "Implement small scripts directly.",
                "model_chain": (
                    {"model_id": "deepseek-flash", "reasoning_effort": "low"},
                ),
            }
        },
        "fingerprint": {"source": "identities.json", "digest": "feed1234feed1234"},
    }

    def test_identity_resolves_model_route_in_payload_and_handoff(self):
        payload = build_coding_delegation_payload(
            "implement the risky refactor",
            executor_target="codex",
            explicit_owner_choice=True,
            requested_identity="script-coding",
            identity_config=self._IDENTITY_CONFIG,
        )
        route = payload["model_route"]
        self.assertEqual(route["identity_id"], "script-coding")
        self.assertEqual(route["identity_fingerprint"]["digest"], "feed1234feed1234")
        self.assertEqual(route["selected_model"], "deepseek-flash")
        self.assertEqual(route["catalog_kind"], "user_identity_config")
        self.assertIn("claim_boundary", route)
        handoff_key = next(k for k in ("executor_handoff", "runtime_handoff", "prompt_handoff") if k in payload)
        self.assertEqual(payload[handoff_key]["model_route"], route)
        self.assertNotIn("Implement small scripts", json.dumps(payload))

    def test_no_identity_keeps_payload_byte_identical(self):
        args = dict(
            executor_target="codex",
            explicit_owner_choice=True,
        )
        with_identity = build_coding_delegation_payload(
            "implement the risky refactor", **args,
            requested_identity="", identity_config=self._IDENTITY_CONFIG,
        )
        without = build_coding_delegation_payload("implement the risky refactor", **args)
        self.assertEqual(with_identity, without)

    def test_external_handoff_request_carries_identity(self):
        prepared = build_external_handoff(
            ExternalHandoffRequest(
                message="implement the risky refactor",
                profile="codex",
                requested_identity="script-coding",
                identity_config=self._IDENTITY_CONFIG,
            )
        )
        route = prepared.payload["model_route"]
        self.assertEqual(route["identity_id"], "script-coding")
        self.assertEqual(prepared.handoff["model_route"]["identity_id"], "script-coding")

    def test_explicit_model_wins_over_identity(self):
        payload = build_coding_delegation_payload(
            "implement the risky refactor",
            executor_target="codex",
            explicit_owner_choice=True,
            requested_model="custom-model",
            requested_identity="script-coding",
            identity_config=self._IDENTITY_CONFIG,
        )
        route = payload["model_route"]
        self.assertEqual(route["selected_model"], "custom-model")
        self.assertEqual(route["provenance"], "request_named_model")
        self.assertEqual(route["identity_id"], "script-coding")


class IdentityRouteProvenanceTest(unittest.TestCase):
    """Provenance records carry `identity`/`identity_digest` additively."""

    def test_identity_fields_survive_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            omh_home = Path(tmp) / "omh"
            omh_home.mkdir()
            append_delegation_route_provenance(
                {
                    "origin": "head",
                    "category": "",
                    "alias": "deepseek-flash",
                    "wire_model": "deepseek-flash",
                    "provider": "",
                    "reasoning_effort": "low",
                    "session_id": "S",
                    "written_at": time.time(),
                    "identity": "script-coding",
                    "identity_digest": "abcd1234abcd1234",
                },
                omh_home,
            )
            record = load_delegation_route_provenance(omh_home)[-1]
            self.assertEqual(record["identity"], "script-coding")
            self.assertEqual(record["identity_digest"], "abcd1234abcd1234")

    def test_records_without_identity_stay_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            omh_home = Path(tmp) / "omh"
            omh_home.mkdir()
            append_delegation_route_provenance(
                {
                    "origin": "head",
                    "category": "deep",
                    "alias": "deep-head",
                    "wire_model": "deep-head",
                    "provider": "",
                    "reasoning_effort": "high",
                    "session_id": "S",
                    "written_at": time.time(),
                },
                omh_home,
            )
            record = load_delegation_route_provenance(omh_home)[-1]
            self.assertNotIn("identity", record)


class DelegateRouteIdentityDefaultBackendTest(unittest.TestCase):
    """`omh_delegate_route set --identity` under the default backend."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.homes = _fresh(temporary)
        self.homes.write_identities(IDENTITIES_TWO_CHAINS)

    def _call(self, session: str | None = None, task: str | None = None, **args) -> dict:
        dispatch = {}
        if session is not None:
            dispatch["session_id"] = session
        if task is not None:
            dispatch["task_id"] = task
        return json.loads(
            omh_delegate_route_handler({**args, **self.homes.homes()}, **dispatch)
        )

    def test_set_identity_routes_chain_head_and_records_metadata(self):
        result = self._call(session="S", task="t1", action="set", identity="alpha")
        self.assertEqual(result["status"], "routed", result)
        self.assertEqual(result["identity"], "alpha")
        self.assertTrue(result["identity_digest"])
        keys = read_delegation_route(self.homes.hermes)
        self.assertEqual(keys["model"], "alpha-head")
        self.assertEqual(keys["reasoning_effort"], "high")
        provenance = load_delegation_route_provenance(self.homes.omh)[-1]
        self.assertEqual(provenance["identity"], "alpha")
        self.assertEqual(provenance["origin"], "head")
        self.assertEqual(result["conversation_route"], "recorded")
        self.assertEqual(
            [c["model"] for c in result["fallback_candidates"]],
            [],
        )

    def test_set_identity_explicit_model_still_wins(self):
        result = self._call(
            session="S", task="t1", action="set", identity="alpha", model="custom-m"
        )
        self.assertEqual(result["status"], "routed", result)
        self.assertEqual(result["applied"]["model"], "custom-m")
        self.assertNotIn("identity", result)
        provenance = load_delegation_route_provenance(self.homes.omh)[-1]
        self.assertNotIn("identity", provenance)
        self.assertEqual(provenance["origin"], "explicit")

    def test_unknown_identity_is_choice_required_not_fallback(self):
        result = self._call(session="S", task="t1", action="set", identity="ghost")
        self.assertEqual(result["status"], "choice_required")
        self.assertEqual(result["reason"], "unknown_identity")
        self.assertEqual(result["identity"], "ghost")
        self.assertEqual(result["available_identities"], ["alpha", "beta"])
        self.assertEqual(read_delegation_route(self.homes.hermes), {})
        self.assertEqual(load_delegation_route_provenance(self.homes.omh), [])

    def test_status_lists_identities(self):
        result = self._call(action="status")
        self.assertEqual(
            sorted(result["identities"]),
            ["alpha", "beta"],
        )
        self.assertTrue(result["identities_fingerprint"])

    def test_identity_fallback_advances_within_identity_chain(self):
        doc = {
            "schema_version": "omh_identity_profiles/v1",
            "identities": {
                "lane": {
                    "prompt": "p",
                    "model_chain": [
                        {"model_id": "lane-head", "reasoning_effort": "high"},
                        {"model_id": "lane-next", "reasoning_effort": "high"},
                    ],
                },
            },
        }
        self.homes.write_identities(doc)
        self._call(session="S", task="t1", action="set", identity="lane")
        result = self._call(session="S", task="t1", action="fallback")
        self.assertEqual(result["status"], "fell_back", result)
        self.assertEqual(result["identity"], "lane")
        keys = read_delegation_route(self.homes.hermes)
        self.assertEqual(keys["model"], "lane-next")
        provenance = load_delegation_route_provenance(self.homes.omh)[-1]
        self.assertEqual(provenance["identity"], "lane")
        self.assertEqual(provenance["origin"], "fallback")

    def test_identity_fallback_never_crosses_into_mixture_category(self):
        # beta-head is unique to the beta identity; a fallback must not
        # continue into a category chain that happens to share the model.
        self._call(session="S", task="t1", action="set", identity="beta")
        result = self._call(session="S", task="t1", action="fallback")
        # beta's chain has one entry, so the lane is exhausted, not misrouted.
        self.assertEqual(result["status"], "exhausted_to_inherit", result)
        self.assertEqual(result["identity"], "beta")

    def test_identity_fallback_detects_config_change(self):
        self._call(session="S", task="t1", action="set", identity="beta")
        # Edit identities.json between the set and the fallback.
        self.homes.write_identities(
            {
                "schema_version": "omh_identity_profiles/v1",
                "identities": {
                    "beta": {
                        "prompt": "Beta prompt v2.",
                        "model_chain": [
                            {"model_id": "beta-head", "reasoning_effort": "low"},
                            {"model_id": "beta-next", "reasoning_effort": "low"},
                        ],
                    },
                },
            }
        )
        result = self._call(session="S", task="t1", action="fallback")
        self.assertEqual(result["status"], "choice_required")
        self.assertEqual(result["reason"], "identity_config_changed")
        self.assertEqual(result["identity"], "beta")
        self.assertNotEqual(result["frozen_digest"], result["current_digest"])

    def test_identity_fallback_reports_deleted_identity(self):
        self._call(session="S", task="t1", action="set", identity="beta")
        self.homes.write_identities(
            {"schema_version": "omh_identity_profiles/v1", "identities": {}}
        )
        result = self._call(session="S", task="t1", action="fallback")
        self.assertEqual(result["status"], "choice_required")
        self.assertEqual(result["reason"], "identity_unavailable")

    def test_clear_restores_baseline_after_identity_route(self):
        self._call(session="S", task="t1", action="set", identity="alpha")
        cleared = self._call(session="S", task="t1", action="clear")
        self.assertEqual(cleared["status"], "cleared", cleared)
        self.assertEqual(read_delegation_route(self.homes.hermes), {})


class DelegateRouteIdentityPerConversationTest(unittest.TestCase):
    """Identity routes are conversation-bound exactly like category routes."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.homes = _fresh(temporary)
        self.homes.write_identities(IDENTITIES_TWO_CHAINS)
        write_sessions(
            self.homes.hermes,
            row("B", last_activity_at=time.time()),
            row("C", last_activity_at=time.time()),
        )

    def tool(self, session: str | None, task: str | None, **args) -> dict:
        dispatch = {}
        if session is not None:
            dispatch["session_id"] = session
        if task is not None:
            dispatch["task_id"] = task
        return json.loads(
            omh_delegate_route_handler({**args, **self.homes.homes()}, **dispatch)
        )

    def set_route(self, session: str, task: str, identity: str) -> dict:
        result = self.tool(session, task, action="set", identity=identity)
        self.assertEqual(result["status"], "routed", result)
        self.assertEqual(result["conversation_route"], "recorded", result)
        return result

    def dispatch(self, session: str, task: str, **args):
        return pre_tool_call(
            tool_name="delegate_task",
            args={"goal": "lane", **args},
            session_id=session,
            task_id=task,
            tool_call_id=f"{session}-{task}-call",
            turn_id=f"{session}-{task}-turn",
            **self.homes.homes(),
        )

    def keys(self) -> dict[str, str]:
        return read_delegation_route(self.homes.hermes)

    def test_two_sessions_different_identities_no_cross_talk(self):
        self.set_route("A", "A-t1", "alpha")
        self.set_route("B", "B-t1", "beta")
        self.assertEqual(self.keys()["model"], "beta-head")

        self.assertIsNone(self.dispatch("A", "A-t1"))
        self.assertEqual(self.keys()["model"], "alpha-head")
        newest = load_delegation_route_provenance(self.homes.omh)[-1]
        self.assertEqual((newest["alias"], newest["session_id"]), ("alpha-head", "A"))
        self.assertEqual(newest["identity"], "alpha")

        self.assertIsNone(self.dispatch("B", "B-t1"))
        self.assertEqual(self.keys()["model"], "beta-head")

    def test_repeated_dispatch_same_session_reapplies_identity_route(self):
        self.set_route("A", "A-t1", "alpha")
        self.assertIsNone(self.dispatch("A", "A-t1"))
        self.assertEqual(self.keys()["model"], "alpha-head")
        # Second dispatch after another session touched the keys: A's own
        # conversation route is restored, not B's.
        self.set_route("B", "B-t1", "beta")
        self.assertIsNone(self.dispatch("A", "A-t1"))
        self.assertEqual(self.keys()["model"], "alpha-head")

    def test_turn_end_takes_back_only_the_writing_sessions_route(self):
        self.set_route("A", "A-t1", "alpha")
        self.set_route("B", "B-t1", "beta")
        ended = on_session_end(session_id="B", task_id="B-t1", **self.homes.homes())
        self.assertEqual(ended["route_restore"]["status"], "cleared", ended)
        self.assertEqual(self.keys(), {})
        self.assertIsNone(self.dispatch("A", "A-t1"))
        self.assertEqual(self.keys()["model"], "alpha-head")
        self.assertEqual(set(load_conversation_routes(self.homes.omh)), {"A"})

    def test_unrouted_dispatch_never_runs_on_another_sessions_identity_route(self):
        self.set_route("B", "B-t1", "beta")
        self.assertIsNone(self.dispatch("C", "C-t1"))
        self.assertEqual(self.keys(), {})
        self.assertIsNone(self.dispatch("B", "B-t1"))
        self.assertEqual(self.keys()["model"], "beta-head")

    def test_provenance_records_carry_identity_per_session(self):
        self.set_route("A", "A-t1", "alpha")
        self.set_route("B", "B-t1", "beta")
        records = load_delegation_route_provenance(self.homes.omh)
        by_session = {r["session_id"]: r for r in records}
        self.assertEqual(by_session["A"]["identity"], "alpha")
        self.assertEqual(by_session["B"]["identity"], "beta")
        self.assertNotEqual(by_session["A"]["alias"], by_session["B"]["alias"])


class DelegateRouteIdentityModelMapBackendTest(unittest.TestCase):
    """Under `model_map`, identity chains are matched onto the user's options."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.homes = _fresh(temporary, MODEL_MAP_CONFIG)
        self.homes.write_identities()

    def _call(self, **args) -> dict:
        return json.loads(
            omh_delegate_route_handler(
                {**args, **self.homes.homes()}, session_id="host-session"
            )
        )

    def test_identity_set_names_matching_option_and_writes_nothing(self):
        result = self._call(action="set", identity="script-coding")
        self.assertEqual(result["status"], "option_selected", result)
        self.assertEqual(result["delegation_backend"], "model_map")
        self.assertEqual(result["identity"], "script-coding")
        self.assertEqual(result["option"], "fast-flash")
        self.assertEqual(result["option_chain"][0]["option"], "fast-flash")
        self.assertNotIn("config.yaml", json.dumps(result))
        self.assertEqual(
            (self.homes.hermes / "config.yaml").read_text(encoding="utf-8"),
            MODEL_MAP_CONFIG,
        )
        self.assertEqual(load_delegation_route_provenance(self.homes.omh), [])

    def test_identity_without_matching_option_is_not_applied(self):
        self.homes.write_identities(
            {
                "schema_version": "omh_identity_profiles/v1",
                "identities": {
                    "exotic": {
                        "prompt": "p",
                        "model_chain": [{"model_id": "no-such-model", "reasoning_effort": "xhigh"}],
                    },
                },
            }
        )
        result = self._call(action="set", identity="exotic")
        self.assertEqual(result["status"], "not_applied")
        self.assertEqual(result["reason"], "no_matching_option")
        self.assertEqual(result["identity"], "exotic")
        self.assertIn("available_options", result)

    def test_identity_fallback_advances_across_options(self):
        result = self._call(action="set", identity="script-coding")
        self.assertEqual(result["option"], "fast-flash")
        next_result = self._call(
            action="fallback", identity="script-coding", option="fast-flash"
        )
        # The identity chain's next entry (glm-5.3-flash) has no matching
        # option, so the backend reports exhaustion of the carried options.
        self.assertIn(next_result["status"], {"option_selected", "options_exhausted"})
        # An explicit effort on a fallback is not matched against the lane head,
        # so it must not drop the identity chain the fallback walks.
        effort_result = self._call(
            action="fallback", identity="script-coding", option="fast-flash", reasoning_effort="low"
        )
        self.assertIn(effort_result["status"], {"option_selected", "options_exhausted"}, effort_result)

    def test_unknown_identity_under_model_map_is_choice_required(self):
        result = self._call(action="set", identity="ghost")
        self.assertEqual(result["status"], "choice_required")
        self.assertEqual(result["reason"], "unknown_identity")
        self.assertEqual(
            (self.homes.hermes / "config.yaml").read_text(encoding="utf-8"),
            MODEL_MAP_CONFIG,
        )

    def test_explicit_model_no_option_serves_is_not_replaced_by_identity(self):
        # The explicit model outranks the identity; with no option serving it,
        # the identity's option must not stand in for it.
        result = self._call(action="set", identity="script-coding", model="custom-m")
        self.assertEqual(result["status"], "not_applied", result)
        self.assertEqual(result["reason"], "no_matching_option")
        self.assertNotIn("option", result)
        self.assertEqual(result["identity"], "script-coding")

    def test_explicit_effort_no_option_serves_is_not_replaced_by_identity(self):
        result = self._call(action="set", identity="script-coding", reasoning_effort="zz-nomatch")
        self.assertEqual(result["status"], "not_applied", result)
        self.assertEqual(result["reason"], "no_matching_option")
        self.assertNotIn("option", result)


class DelegateRouteIdentityProfileRoutesBackendTest(unittest.TestCase):
    """Under `profile_routes`, identity selection is typed `not_applied`."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.homes = _fresh(temporary, PROFILE_ROUTES_CONFIG)
        self.homes.write_identities()

    def test_identity_is_not_applied_under_profile_routes(self):
        result = json.loads(
            omh_delegate_route_handler(
                {**self.homes.homes(), "action": "set", "identity": "review"},
                session_id="host-session",
            )
        )
        self.assertEqual(result["status"], "not_applied")
        self.assertEqual(result["reason"], "profile_routes_backend")
        self.assertEqual(result["identity"], "review")
        self.assertEqual(result["profiles"], ["coder", "researcher"])
        self.assertEqual(
            (self.homes.hermes / "config.yaml").read_text(encoding="utf-8"),
            PROFILE_ROUTES_CONFIG,
        )
        self.assertEqual(load_delegation_route_provenance(self.homes.omh), [])


class FingerprintDriftFanoutTest(unittest.TestCase):
    """Prepare-vs-dispatch skew is reported against the right config source."""

    def _contract(self, digest: str) -> dict:
        return {
            "schema_version": "fanout_contract/v1",
            "fanout_id": "fanout-abc123def456",
            "status": "prepared_not_observed",
            "source": "generic",
            "goal": {"summary": "x", "input_chars": 1, "sha256": "0" * 64},
            "units": [
                {
                    "unit_id": "core",
                    "title": "core",
                    "owner": "codex",
                    "boundary": {"file_scope": ["src/"], "do_not_touch": []},
                    "depends_on": [],
                    "run_ref": "fanout-abc123def456-core",
                    "handoff": {
                        "schema_version": "fanout_unit_handoff/v1",
                        "executor_target": "codex",
                        "dispatch_policy": "prepare_only",
                        "status": "prepared_not_observed",
                        "model_route": {
                            "schema_version": "coding_model_route/v2",
                            "executor_profile": "codex",
                            "status": "routed",
                            "provenance": "identity_chain_head",
                            "role": "",
                            "selected_model": "deepseek-flash",
                            "selected_reasoning_effort": "low",
                            "model_family": "deepseek",
                            "chain": [],
                            "attempted": [],
                            "candidates": [],
                            "catalog_kind": "user_identity_config",
                            "identity_id": "script-coding",
                            "identity_fingerprint": {
                                "source": "identities.json",
                                "digest": digest,
                            },
                            "catalog_fingerprint": {
                                "source": "identities.json",
                                "digest": digest,
                            },
                            "reasons": [],
                            "claim_boundary": "prepared route metadata only",
                        },
                        "input_representation": [],
                        "claim_boundary": "prepared guidance only",
                    },
                    "integration_checks": [],
                    "status": "prepared",
                },
            ],
            "merge_plan": {"merge_order": ["core"], "final_integration_gate": [], "conflict_risk_notes": []},
            "board_projection": {"schema_version": "agent_board_card/v1", "unit_ids": ["core"], "status_by_unit": {"core": "prepared"}},
            "observed_evidence_required": [],
            "claim_boundary": "prepared",
        }

    def test_identity_fingerprint_drift_reports_config_source(self):
        from omh.coding.fanout_dispatch import _config_fingerprint_note

        route = self._contract("frozen1111")["units"][0]["handoff"]["model_route"]
        with tempfile.TemporaryDirectory() as tmp:
            omh_home_dir = Path(tmp) / "omh"
            routing = omh_home_dir / "routing"
            routing.mkdir(parents=True)
            (routing / "identities.json").write_text(
                json.dumps(
                    {
                        "schema_version": "omh_identity_profiles/v1",
                        "identities": {
                            "script-coding": {
                                "prompt": "p",
                                "model_chain": [{"model_id": "deepseek-flash"}],
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            class _Paths:
                omh_home: Path = omh_home_dir

            note = _config_fingerprint_note(_Paths(), route)
            self.assertIsNotNone(note)
            assert note is not None
            self.assertEqual(note["source"], "identities.json")
            self.assertEqual(note["frozen_digest"], "frozen1111")
            self.assertFalse(note["match"])

    def test_inventory_fingerprint_stays_inventory_only(self):
        from omh.coding.model_inventory import catalog_fingerprint_note

        route = self._contract("frozen2222")["units"][0]["handoff"]["model_route"]
        # A sourced fingerprint is never compared to the inventory digest.
        self.assertIsNone(catalog_fingerprint_note(route, "any-digest"))
        # An inventory fingerprint (no `source`) still compares as before.
        inv_route = {"catalog_fingerprint": {"digest": "abc"}}
        note = catalog_fingerprint_note(inv_route, "abc")
        self.assertEqual(note["match"], True)


class NestedExplicitMarkerTest(unittest.TestCase):
    """A `[omh-identity:x]` marker in a delegated child's goal selects the
    child's identity through D3's hook; the parent may still set the route."""

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.homes = _fresh(temporary)
        self.homes.write_identities(IDENTITIES_TWO_CHAINS)
        write_sessions(
            self.homes.hermes,
            row("P", last_activity_at=time.time()),
            row("O", parent="P", source="subagent", delegate_from="P", started_at=1050.0),
        )

    def tool(self, session: str | None, task: str | None, **args) -> dict:
        dispatch = {}
        if session is not None:
            dispatch["session_id"] = session
        if task is not None:
            dispatch["task_id"] = task
        return json.loads(
            omh_delegate_route_handler({**args, **self.homes.homes()}, **dispatch)
        )

    def test_nested_child_inherits_parents_identity_route(self):
        routed = self.tool("P", "P-t1", action="set", identity="alpha")
        self.assertEqual(routed["status"], "routed")
        self.assertIsNone(
            pre_tool_call(
                tool_name="delegate_task",
                args={"goal": "[omh-identity:alpha] do the nested thing"},
                session_id="O",
                task_id="O-task",
                tool_call_id="O-call",
                turn_id="O-turn",
                **self.homes.homes(),
            )
        )
        keys = self.keys()
        self.assertEqual(keys["model"], "alpha-head")
        record = load_route_restore_record(self.homes.omh)
        self.assertEqual((record["writer_session_id"], record["writer_task_id"]), ("P", "P-t1"))

    def keys(self) -> dict[str, str]:
        return read_delegation_route(self.homes.hermes)
