from __future__ import annotations

import hashlib
import json
import unittest
from functools import cached_property
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal, TypedDict

from _cli_harness import run_cli
from omh.coding.model_routing import resolve_model_route
from omh.plugin_bundle.omh.hooks.llm_hooks import pre_llm_call

FixtureEvidence = TypedDict("FixtureEvidence", {
    "value": int | None, "class": Literal["observed", "assumed", "unknown"], "source": str, "observed_at": str,
})


class RouteBoundBudgetTests(unittest.TestCase):
    session = "session-a"
    fields = ("context_window_tokens", "max_output_tokens", "compaction_reserve_tokens", "retained_history_tokens")

    @cached_property
    def home(self) -> Path:
        home = Path(self.enterContext(TemporaryDirectory())) / "qa-profile" / "qa-project"
        home.mkdir(parents=True)
        return home

    def capacity(self, values=(128000, 8000, 8000, 32000)) -> dict[str, FixtureEvidence]:
        return {
            name: {"value": value, "class": "observed", "source": "local_fixture", "observed_at": "2026-09-10T00:00:00Z"}
            for name, value in zip(self.fields, values, strict=True)
        }

    def cli(self, *args: str):
        code, stdout, stderr = run_cli(["--omh-home", str(self.home), "context", "budget-plan", *args, "--session-ref", self.session, "--json"])
        self.assertEqual((code, stderr), (0, ""))
        return json.loads(stdout)

    def publish(self, operation="prepare", route="a", capacity: bool | dict[str, FixtureEvidence] = True, tokens=12000,
                digest="a", item_classes=None):
        args = [operation, "--executor-profile", "hermes", "--provider", f"provider-{route}", "--model", f"model-{route}"]
        if capacity:
            data = self.capacity() if capacity is True else capacity
            path = self.home / "capacity.json"
            path.write_text(json.dumps({"schema_version": "route_capacity_input/v1", **data}), encoding="utf-8")
            args += ["--capacity", str(path)]
        if operation == "prepare":
            path = self.home / "must-keep.json"
            # `item_classes` stays absent by default, so every other case in
            # this file publishes the pre-item-class pack shape and the
            # compatibility path is exercised by the whole file, not one test.
            pack: dict[str, object] = {"digest": "sha256:" + digest * 64, "estimated_tokens_total": tokens}
            if item_classes is not None:
                pack["item_classes"] = item_classes
            path.write_text(json.dumps(pack), encoding="utf-8")
            args += ["--must-keep", str(path)]
        return self.cli(*args)

    def hook(self, model="model-a", **kwargs):
        payload = pre_llm_call(omh_home=str(self.home), session_id=self.session, model=model,
                               user_message="continue", is_first_turn=False, **kwargs) or {}
        return json.loads(json.dumps(payload))

    def test_route_evidence_binding(self) -> None:
        # Given explicit, independently classified capacity evidence.
        self.publish()
        # When the public status surface reads the session plan.
        status = self.cli("status")
        # Then exact route metadata, freshness and observed-only arithmetic survive.
        record = status["route_capacity"]
        self.assertEqual(record["route_identity"]["provider"], "provider-a")
        self.assertEqual(record["route_identity"]["wire_model"], "model-a")
        self.assertEqual(record["usable_budget_tokens"], {"value": 80000, "class": "observed"})
        self.assertEqual(record["derivation"]["operation"], "window-output-reserve-retained")
        for name in self.fields:
            self.assertEqual(record["capacity"][name], self.capacity()[name])
        mixed = self.capacity()
        mixed["compaction_reserve_tokens"]["class"] = "assumed"
        mixed["retained_history_tokens"] = {"value": None, "class": "unknown", "source": "unknown", "observed_at": ""}
        assumed = self.capacity()
        assumed["compaction_reserve_tokens"]["class"] = "assumed"
        for data, expected in ((mixed, "unknown"), (assumed, "assumed")):
            with self.subTest(classification=expected):
                result = self.publish(capacity=data)["route_capacity"]
                self.assertEqual(result["usable_budget_tokens"], {"value": None, "class": expected})
                self.assertEqual(result["capacity"]["compaction_reserve_tokens"]["class"], "assumed")

    def test_different_route_capacities(self) -> None:
        # Given route-a with all four allowances represented.
        large = self.publish()
        # When route-b publishes its different effective policy.
        small = self.publish(route="b", capacity=self.capacity((64000, 4000, 4000, 16000)))
        # Then each budget is independently derived, not family/global defaulted.
        self.assertEqual((large["route_capacity"]["usable_budget_tokens"]["value"], small["route_capacity"]["usable_budget_tokens"]["value"]), (80000, 40000))
        self.assertNotEqual(large["route_capacity"]["effective_capacity_digest"], small["route_capacity"]["effective_capacity_digest"])
        self.assertNotEqual(large["route_capacity"]["route_identity_digest"], small["route_capacity"]["route_identity_digest"])

    def test_smaller_route_requires_checkpoint(self) -> None:
        # Given a session plan published at the control-plane boundary.
        # An actual host-only route change must already produce recovery even
        # when no new CLI/capacity implementation exists.
        directory = self.home / "runtime" / "context-budget-plans"
        directory.mkdir(parents=True)
        path = directory / (hashlib.sha256(self.session.encode()).hexdigest() + ".json")
        path.write_text(json.dumps({"schema_version": "context_budget_plan/v1", "route_capacity": {"route_identity": {"wire_model": "model-a"}}}))
        # When the host changes models before any capacity publication.
        payload = self.hook("model-b")
        # Then the real continuation seam exposes a bounded recovery obligation.
        self.assertIn("omh_context_budget", payload)
        self.assertEqual(payload["omh_context_budget"]["invalidation"]["action"], "capacity_unknown_hold")
        for tokens, action in ((12000, "checkpoint_required"), (50000, "overflow_recovery_required")):
            with self.subTest(tokens=tokens):
                self.publish(tokens=tokens)
                smaller = self.publish("rebind", "b", self.capacity((64000, 4000, 4000, 16000)))
                result = self.hook("model-b")["omh_context_budget"]
                self.assertTrue(result["stale"])
                self.assertEqual(result["invalidation"]["action"], action)
                self.assertEqual(result["must_keep_pack"], smaller["must_keep_pack"])
                self.assertEqual(result["recovery"]["max_checkpoint_attempts"], 1)
                self.assertIn("[OMH Context Budget]", self.hook("model-b")["context"])
                # Repeating rebind cannot accidentally discharge pending recovery.
                self.publish("rebind", "b", self.capacity((64000, 4000, 4000, 16000)))
                self.assertEqual(self.hook("model-b")["omh_context_budget"]["invalidation"]["action"], action)

    def test_equivalent_capacity_preserves_pack(self) -> None:
        # Given a prepared route-a plan with a stable must-keep digest.
        before = self.publish()
        # When only wire/provider identity and evidence timestamp change.
        same = self.capacity()
        same["context_window_tokens"]["observed_at"] = "2026-09-10T01:00:00Z"
        after = self.publish("rebind", "x", same)
        # Then capacity equality preserves the plan, not the old route identity.
        self.assertEqual(after["plan_id"], before["plan_id"])
        self.assertEqual(after["must_keep_pack"], before["must_keep_pack"])
        self.assertFalse(after["stale"])
        self.assertEqual(after["invalidation"], {"reason": "none", "action": "continue"})
        self.assertEqual(after["route_capacity"]["route_identity"]["wire_model"], "model-x")
        self.assertEqual(after["route_history"][-1], before["route_capacity"]["route_identity_digest"])
        self.assertEqual(self.hook("model-x")["omh_context_budget"]["plan_id"], before["plan_id"])

    def test_unknown_limits_do_not_inherit(self) -> None:
        # Given an observed plan on a different provider/model.
        self.publish()
        # When the new route has no eligible evidence.
        unknown = self.publish("rebind", "unknown", False)
        # Then every absent field is unknown and the hook never borrows capacity.
        for name in self.fields:
            self.assertEqual(unknown["route_capacity"]["capacity"][name]["value"], None)
            self.assertEqual(unknown["route_capacity"]["capacity"][name]["class"], "unknown")
        result = self.hook("model-unknown")["omh_context_budget"]
        self.assertEqual(result["invalidation"]["action"], "capacity_unknown_hold")
        self.assertIsNone(result["usable_budget_tokens"]["value"])
        self.publish()
        for model in ("model-other", "", "provider-a/model-a"):
            with self.subTest(model=model):
                changed = self.hook(model)["omh_context_budget"]
                self.assertEqual(changed["invalidation"]["action"], "capacity_unknown_hold")
                self.assertIsNone(changed["usable_budget_tokens"]["value"])
                self.assertIsNone(changed["host_route"]["provider"])
        self.assertNotIn("omh_context_budget", pre_llm_call(omh_home=str(self.home), session_id="session-b", model="model-a") or {})

    def test_status_keeps_observation_boundaries(self) -> None:
        # Given a prepared plan without usage, billing or compaction receipts.
        self.publish()
        before = self.cli("status")
        self.publish("rebind", "b", self.capacity((64000, 4000, 4000, 16000)))
        # When status is requested after invalidation.
        after = self.cli("status")
        # Then the active source/reason changes, while independent clocks stay absent.
        self.assertNotEqual(before["active_budget_source"], after["active_budget_source"])
        self.assertEqual(after["invalidation"]["reason"], "capacity_shrank")
        for result in (before, after, self.hook("model-b")["omh_context_budget"]):
            self.assertEqual(result["provider_usage_observed"], "not_observed")
            self.assertEqual(result["compaction_observed"], "not_observed")
            self.assertEqual(result["billing_observed"], "not_observed")
            self.assertIsNone(result["observation_clocks"]["provider_usage"])
            self.assertIsNone(result["observation_clocks"]["compaction"])
        self.assertEqual(after["local_token_estimate"]["class"], "assumed")

    def test_routing_and_cache_regression(self) -> None:
        # Given the real resolver and an idle hook with no session plan.
        route = resolve_model_route("hermes", requested_model="provider-a/model-a")
        self.assertEqual(route["selected_model"], "provider-a/model-a")
        self.assertNotIn("omh_context_budget", self.hook())
        self.publish()
        first = self.hook()
        # When the real host replays history and a plan's stable projection.
        replay = self.hook(conversation_history=[{"role": "user", "content": "continue", "api_content": "continue\n" + first["context"]}])
        # Then replay is byte-stable and ordinary model routing remains pure.
        self.assertIn("omh_context_budget", replay)
        self.assertEqual(replay, first)
        self.assertEqual(resolve_model_route("hermes", requested_model="provider-a/model-a"), route)
        self.assertEqual(replay["omh_context_budget"]["host_route"]["provider"], None)
        self.assertEqual(replay["omh_context_budget"]["provider_usage_observed"], "not_observed")
        self.assertNotIn("omh_context_budget", self.hook(include_omh_awareness=False))

    def test_rebind_loop_is_bounded(self) -> None:
        # Given a repeated fallback between two known policies.
        first = self.publish()
        for index in range(10):
            self.publish("rebind", str(index), self.capacity((64000 + index, 4000, 4000, 16000)))
        # When the next continuation boundary runs after the bounded lineage.
        result = self.hook("model-9")["omh_context_budget"]
        # Then it holds without attempting compaction or discarding the pack.
        self.assertEqual(result["invalidation"]["action"], "rebind_loop_hold")
        self.assertEqual(result["must_keep_pack"], first["must_keep_pack"])
        status = self.cli("status")
        self.assertEqual(status["rebind_count"], 9)
        self.assertEqual(len(status["route_history"]), 8)

    def test_invalid_capacity_is_rejected_without_publication(self) -> None:
        # Given a valid publication and adversarial JSON capacity inputs.
        self.publish()
        plans = self.home / "runtime" / "context-budget-plans"
        before = {p.name: p.read_bytes() for p in plans.glob("*.json")}
        inputs = ["[]", '{"schema_version":"unsupported"}', json.dumps({"schema_version": "route_capacity_input/v1", "prompt": "PRIVATE_SENTINEL"})]
        for value, kind, clock in ((True, "observed", "2026-09-10T00:00:00Z"), (-1, "assumed", ""), (1, "unknown", ""), (1, "observed", "")):
            inputs.append(json.dumps({"schema_version": "route_capacity_input/v1", "context_window_tokens": {"value": value, "class": kind, "source": "fixture", "observed_at": clock}}))
        for raw in inputs:
            with self.subTest(raw=raw):
                path = self.home / "invalid.json"
                path.write_text(raw)
                # When untrusted evidence crosses the real CLI parser.
                code, stdout, stderr = run_cli(["--omh-home", str(self.home), "context", "budget-plan", "rebind", "--session-ref", self.session, "--executor-profile", "hermes", "--provider", "p", "--model", "m", "--capacity", str(path), "--json"])
                # Then there is an explicit error, no leaked input and no write.
                self.assertEqual(code, 2)
                self.assertNotIn("PRIVATE_SENTINEL", stdout + stderr)
                self.assertEqual({p.name: p.read_bytes() for p in plans.glob("*.json")}, before)

    def test_corrupt_binding_never_projects_prior_capacity(self) -> None:
        for corruption in ("digest", "session", "json"):
            with self.subTest(corruption=corruption):
                # Given an independently corrupted on-disk binding.
                plan = self.publish()
                path = next((self.home / "runtime" / "context-budget-plans").glob("*.json"))
                if corruption == "digest":
                    plan["route_capacity"]["effective_capacity_digest"] = "sha256:" + "f" * 64
                if corruption == "session":
                    plan["session_ref"] = "sha256:" + "f" * 64
                path.write_text("[" * 2000 + "0" + "]" * 2000 if corruption == "json" else json.dumps(plan))
                # When the next host call reads that session record.
                projection = self.hook()["omh_context_budget"]
                # Then it exposes recovery, not old capacity or untrusted content.
                self.assertEqual(projection["invalidation"]["action"], "capacity_unknown_hold")
                self.assertIsNone(projection["active_budget_source"])
                self.assertIsNone(projection["usable_budget_tokens"]["value"])

    def test_replaced_pack_names_the_item_class_that_went_missing(self) -> None:
        # Given a pack that recorded what it was keeping, by class.
        recorded = {
            "prohibitions": {"count": 2, "refs": ["no-force-push", "no-schema-rewrite"]},
            "decisions": {"count": 1, "refs": ["adr-0007"]},
            "open_questions": {"count": 1, "refs": ["q-rollback-owner"]},
        }
        first = self.publish(item_classes=recorded)
        self.assertEqual(first["must_keep_delta"]["comparison"], "unavailable")
        self.assertEqual(first["must_keep_delta"]["unavailable_reason"], "no_previous_pack")
        # When a later preparation drops one class outright and thins another.
        survives = {
            "prohibitions": {"count": 1, "refs": ["no-force-push"]},
            "decisions": {"count": 1, "refs": ["adr-0007"]},
        }
        second = self.publish(digest="b", item_classes=survives)
        delta = second["must_keep_delta"]
        # Then the report names the class, not only that the digest differs.
        self.assertFalse(delta["digest_matches"])
        self.assertEqual(delta["comparison"], "compared")
        self.assertEqual(delta["missing_classes"], ["open_questions"])
        self.assertEqual(
            delta["reduced_classes"],
            [{"item_class": "prohibitions", "previous_count": 2, "current_count": 1, "dropped_refs": ["no-schema-rewrite"]}],
        )
        # And an unchanged class is not reported as a loss.
        self.assertNotIn("decisions", [row["item_class"] for row in delta["reduced_classes"]])

    def test_pack_without_item_classes_reports_unavailable_not_empty(self) -> None:
        # Given a plan published before item classes existed on the pack.
        self.publish()
        stored = self.cli("status")["must_keep_pack"]
        self.assertIsNone(stored["item_classes"])
        # When a class-recording pack replaces it, and then the reverse.
        forward = self.publish(digest="b", item_classes={"prohibitions": {"count": 1, "refs": ["no-force-push"]}})
        backward = self.publish(digest="c")
        # Then neither direction claims the missing side lost nothing.
        for payload, reason in (
            (forward, "previous_pack_recorded_no_item_classes"),
            (backward, "current_pack_recorded_no_item_classes"),
        ):
            with self.subTest(reason=reason):
                delta = payload["must_keep_delta"]
                self.assertEqual(delta["comparison"], "unavailable")
                self.assertEqual(delta["unavailable_reason"], reason)
                self.assertEqual((delta["missing_classes"], delta["reduced_classes"]), ([], []))

    def test_item_classes_stay_metadata_only(self) -> None:
        # Given packs carrying an unknown class, prose refs, and count/ref drift.
        rejected = (
            {"secrets": {"count": 1, "refs": ["x"]}},
            {"prohibitions": {"count": 1}},
            {"prohibitions": {"count": 1, "refs": ["do not rewrite the PRIVATE_SENTINEL schema"]}},
            {"prohibitions": {"count": 1, "refs": ["a", "b"]}},
            {"prohibitions": {"count": 1, "refs": ["a", "a"]}},
            {"prohibitions": {"count": 2, "refs": ["a"] * 9}},
        )
        plans = self.home / "runtime" / "context-budget-plans"
        self.publish()
        before = {p.name: p.read_bytes() for p in plans.glob("*.json")}
        for classes in rejected:
            with self.subTest(classes=classes):
                path = self.home / "bad-pack.json"
                path.write_text(json.dumps({"digest": "sha256:" + "b" * 64, "estimated_tokens_total": 10, "item_classes": classes}))
                # When the untrusted pack crosses the real CLI parser.
                code, stdout, stderr = run_cli([
                    "--omh-home", str(self.home), "context", "budget-plan", "prepare", "--session-ref", self.session,
                    "--executor-profile", "hermes", "--provider", "p", "--model", "m", "--must-keep", str(path), "--json",
                ])
                # Then it is refused with no leaked text and no publication.
                self.assertEqual(code, 2)
                self.assertNotIn("PRIVATE_SENTINEL", stdout + stderr)
                self.assertEqual({p.name: p.read_bytes() for p in plans.glob("*.json")}, before)
