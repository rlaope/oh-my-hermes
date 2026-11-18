"""Undecidable routes hand their shortlist to model selection.

The deterministic router keeps every confident route. These tests pin the other
half: a tie, a near-tie, a low-confidence score, or a script the trigger tables
do not cover must produce candidates for the model to choose from instead of a
picker or a bare fallback.
"""

from __future__ import annotations

import json
import unittest
from typing import Any

from omh.routing.candidate_handoff import (
    CANDIDATE_HANDOFF_SCHEMA_VERSION,
    MAX_CANDIDATES,
    REASON_LOW_CONFIDENCE,
    REASON_NARROW_SCORE_GAP,
    REASON_NO_TRIGGER_COVERAGE,
    build_candidate_handoff,
    candidate_handoff_digest,
)
from omh.routing.chat import route_chat_message


class CandidateHandoffTests(unittest.TestCase):
    def test_a_confident_route_carries_no_handoff(self) -> None:
        route = route_chat_message("why is the build failing on main?", source="generic", limit=3)

        self.assertEqual(route["action"], "dispatch")
        self.assertIsNone(route.get("candidate_handoff"))

    def test_a_scoring_tie_hands_the_shortlist_over(self) -> None:
        # Two skills scored 9 apiece here, so the picker was standing in for a
        # decision the scorer could not make.
        route = route_chat_message("PR 리뷰 좀 해줘", source="generic", limit=3)
        handoff = route["candidate_handoff"]

        self.assertEqual(route["action"], "clarify")
        self.assertEqual(handoff["schema_version"], CANDIDATE_HANDOFF_SCHEMA_VERSION)
        self.assertIn(REASON_NARROW_SCORE_GAP, handoff["reasons"])
        self.assertIn("code-review", [candidate["skill"] for candidate in handoff["candidates"]])
        self.assertEqual(handoff["selector"], "hermes")

    def test_a_script_without_trigger_coverage_hands_over(self) -> None:
        # Hindi, not Japanese or Russian: this case used to use "ビルドが失敗した理由を教えて"
        # back when Kana had no trigger table, then a Russian sentence. Shipping
        # `trigger_packs/ja.json` and then `ru.json` gave each script a table, so
        # those sentences are now covered and would not exercise this path. What is being pinned is the
        # behavior for a script no pack covers, so the case has to move to one.
        route = route_chat_message("main पर बिल्ड क्यों फेल हो रहा है", source="generic", limit=3)
        handoff = route["candidate_handoff"]

        self.assertIn(REASON_NO_TRIGGER_COVERAGE, handoff["reasons"])
        self.assertIn(REASON_LOW_CONFIDENCE, handoff["reasons"])

    def test_every_candidate_carries_its_reason_and_evidence_boundary(self) -> None:
        route = route_chat_message("PR 리뷰 좀 해줘", source="generic", limit=3)

        for candidate in route["candidate_handoff"]["candidates"]:
            with self.subTest(skill=candidate["skill"]):
                self.assertTrue(candidate["skill"])
                self.assertTrue(candidate["why_it_matched"])
                self.assertTrue(candidate["next_action"])
                self.assertTrue(candidate["evidence_boundary"])
                self.assertIn(candidate["reasoning_demand"], {"light", "standard", "heavy"})

    def test_the_candidate_set_is_bounded(self) -> None:
        route = route_chat_message("PR 리뷰 좀 해줘", source="generic", limit=8)

        self.assertLessEqual(route["candidate_handoff"]["candidate_count"], MAX_CANDIDATES)

    def test_the_handoff_is_reproducible(self) -> None:
        first = route_chat_message("PR 리뷰 좀 해줘", source="generic", limit=3)["candidate_handoff"]
        second = route_chat_message("PR 리뷰 좀 해줘", source="generic", limit=3)["candidate_handoff"]

        self.assertEqual(first["digest"], second["digest"])

    def test_the_digest_tracks_the_shortlist_not_the_scores(self) -> None:
        reasons = (REASON_NARROW_SCORE_GAP,)
        low = candidate_handoff_digest([{"skill": "code-review", "score": 9}], reasons)
        high = candidate_handoff_digest([{"skill": "code-review", "score": 41}], reasons)
        other = candidate_handoff_digest([{"skill": "verification-gate", "score": 9}], reasons)

        self.assertEqual(low, high)
        self.assertNotEqual(low, other)

    def test_an_empty_shortlist_points_at_the_catalog_index(self) -> None:
        route = {
            "action": "fallback",
            "confidence": "low",
            "recommendations": [],
            "input_language": {"trigger_support": "model_selection_required"},
        }
        handoff = build_candidate_handoff(route)

        self.assertEqual(handoff["candidate_count"], 0)
        self.assertEqual(handoff["catalog_reference"], "references/catalog-index.md")
        self.assertIn("catalog-index", str(handoff["question"]))

    def test_the_handoff_never_claims_a_decision(self) -> None:
        route = route_chat_message("PR 리뷰 좀 해줘", source="generic", limit=3)

        self.assertIn("not a routing decision", route["candidate_handoff"]["claim_boundary"])


class CodingLaneTests(unittest.TestCase):
    """An implementation-shaped request gets the coding lane, not scorer noise.

    Observed live: "...백엔드 구현해줘" reached model selection carrying
    instinct-ledger, materials-package, and memory-new at score 3 -- decomposed
    -token noise -- while the engine that delivers coding work (ultrawork)
    never surfaced. The same session's picker offered
    idea-to-deploy and planning flows for what was an implementation ask.

    The original message now has a real owner: the `backend` workflow claims
    server-side requests and prepares the service contract whose handoff names
    the executor, which is the outcome the lane existed to approximate. The
    fixtures below drop the domain word so they still exercise the case the
    lane is for -- an implementation-shaped request that reaches no owner --
    and `test_a_domain_request_reaches_its_domain_workflow` pins the other
    half, so a `backend` trigger regression cannot look like a pass.
    """

    LANE = ["ultrawork", "executor-runtime-readiness"]
    OWNERLESS_IMPLEMENTATION_ASK = (
        "document-harness에서 프로젝트 링크만 주면 observer 결과를 자동 조회하게 구현해줘"
    )

    def _handoff(self, message: str) -> dict:
        from omh.routing.chat import route_chat_message

        return route_chat_message(message, source="slack").get("candidate_handoff") or {}

    def test_the_observed_failure_now_yields_the_coding_lane(self) -> None:
        handoff = self._handoff(self.OWNERLESS_IMPLEMENTATION_ASK)
        self.assertEqual([c["skill"] for c in handoff["candidates"]], self.LANE)
        self.assertEqual(handoff["candidates"][0]["reasoning_demand"], "heavy")
        self.assertIn("implementation_shaped_request", handoff["reasons"])
        self.assertIn("Do not route implementation work to planning-only flows", handoff["question"])

    def test_english_implementation_asks_now_dispatch_the_delivery_engine(self) -> None:
        # #954 stage 5: `ultrawork` absorbed the delivery vocabulary, so the
        # English phrasing that used to stall into the candidate lane now
        # dispatches directly -- the lane stays reserved for requests that
        # still reach no owner (the Korean case above).
        from omh.routing.chat import route_chat_message

        # Shortlist-first (2026-09-26): `implement` alone is a token, so this
        # now asks. FINDING: ultrawork is not the top shortlist entry here
        # (the lexical ranking leads with harness-session-inventory on
        # "document-harness"); what holds is that nothing is dispatched.
        route = route_chat_message("implement the observer lookup for document-harness", source="slack")
        self.assertEqual(route["action"], "clarify")
        self.assertIn("candidate_handoff", route)

    def test_a_domain_request_reaches_its_domain_workflow(self) -> None:
        # The other half of the lane guard. A server-side request now has an
        # owner that prepares the auth boundary, error paths, and migration
        # order before the executor is handed the work, so it must not fall
        # back into the generic delivery lane.
        from omh.routing.chat import route_chat_message

        # Shortlist-first: the name `backend` is one word, so this asks, with
        # backend leading the shortlist rather than the delivery lane.
        route = route_chat_message("implement the backend for observer lookup", source="slack")
        self.assertEqual(route["action"], "clarify")
        self.assertEqual(route["candidate_skill"], "backend")

    def test_a_strong_match_keeps_its_own_shortlist(self) -> None:
        # The lane replaces noise, never signal: a real trigger match must not
        # be displaced by generic coding candidates.
        from omh.routing.chat import route_chat_message

        route = route_chat_message("기억이 잘못 저장된 것 같아 확인해줘", source="slack")
        self.assertEqual(route["action"], "dispatch")
        self.assertNotIn("candidate_handoff", route)

    def test_non_coding_weak_requests_do_not_get_the_lane(self) -> None:
        handoff = self._handoff("점심 뭐 먹을까 추천해줘")
        skills = [c["skill"] for c in handoff.get("candidates", [])]
        self.assertNotEqual(skills, self.LANE)
        self.assertNotIn("implementation_shaped_request", handoff.get("reasons", []))

    def test_lane_candidates_carry_the_routing_only_boundary(self) -> None:
        handoff = self._handoff(self.OWNERLESS_IMPLEMENTATION_ASK)
        for candidate in handoff["candidates"]:
            self.assertIn("routing input only", candidate["evidence_boundary"])


class WrapperPathParityTests(unittest.TestCase):
    """The messenger path sees the same enriched route as a direct call.

    Found by a mocked Slack QA pass: `_public_chat_route_payload_cached` called
    the raw cached decision directly, so the wrapper contract -- and therefore
    every messenger behind `omh_interact` -- never received `input_language`,
    the model-selection `candidate_handoff`, or skill governance. The
    candidate-handoff feature was invisible on the one surface it was built
    for.
    """

    # The domain word is out for the same reason as `CodingLaneTests`: the
    # `backend` workflow now owns server-side requests, and this test is about
    # the wrapper path carrying the handoff, not about which lane claims a
    # domain ask.
    MESSAGE = "document-harness에서 프로젝트 링크만 주면 observer 결과를 자동 조회하게 구현해줘"

    def test_the_public_payload_carries_the_handoff_and_language(self) -> None:
        from omh.routing.chat import public_chat_route_payload

        route = public_chat_route_payload(self.MESSAGE, source="slack")
        handoff = route.get("candidate_handoff") or {}
        self.assertEqual(
            [candidate["skill"] for candidate in handoff.get("candidates", [])],
            ["ultrawork", "executor-runtime-readiness"],
        )
        self.assertIn("input_language", route)
        self.assertTrue(
            all(
                candidate["reasoning_demand"] in {"light", "standard", "heavy"}
                for candidate in handoff.get("candidates", [])
            )
        )
        self.assertTrue(
            all(
                recommendation["reasoning_demand"] in {"light", "standard", "heavy"}
                for recommendation in route.get("recommendations", [])
            )
        )

    def test_the_real_plugin_tool_route_matches_the_direct_route(self) -> None:
        import json as jsonlib
        import os
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch

        from omh.plugin_bundle.omh.tools.chat_tool import omh_interact_handler
        from omh.routing.chat import route_chat_message

        direct = route_chat_message(self.MESSAGE, source="slack")
        direct_lane = [c["skill"] for c in (direct.get("candidate_handoff") or {}).get("candidates", [])]
        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.dict(os.environ, {"OMH_HOME": str(root / ".omh"), "HERMES_HOME": str(root / ".hermes")}):
                out = jsonlib.loads(
                    omh_interact_handler(
                        {
                            "message": self.MESSAGE,
                            "source": "slack",
                            "record_session": False,
                            "omh_home": str(root / ".omh"),
                            "hermes_home": str(root / ".hermes"),
                        }
                    )
                )
        tool_route = out.get("route") or {}
        tool_lane = [c["skill"] for c in (tool_route.get("candidate_handoff") or {}).get("candidates", [])]
        self.assertEqual(tool_lane, direct_lane)
        self.assertIn("input_language", tool_route)

    def _plugin_ulw_interaction(
        self,
        root,
        *,
        model: str,
        workflow: str = "ultrawork",
    ) -> dict[str, Any]:
        from omh.plugin_bundle.omh.hooks.llm_hooks import pre_llm_call
        from omh.plugin_bundle.omh.tools.chat_tool import omh_interact_handler

        message = f"${workflow} implement src/example.py end to end"
        pre_llm_call(
            user_message=message,
            is_first_turn=False,
            model=model,
            source="discord",
            omh_home=str(root / ".omh"),
            hermes_home=str(root / ".hermes"),
        )
        return json.loads(
            omh_interact_handler(
                {
                    "message": message,
                    "source": "discord",
                    "mode": "route",
                    "executor_target": "hermes",
                    "record_session": False,
                    "omh_home": str(root / ".omh"),
                    "hermes_home": str(root / ".hermes"),
                }
            )
        )

    @staticmethod
    def _without_catalog_candidates(interaction: dict[str, Any]) -> dict[str, Any]:
        """Remove shipped skipped candidates before checking live-model leakage."""
        import copy

        stripped = copy.deepcopy(interaction)
        binding = stripped["delegation"]["runtime_handoff"]["hermes_native_model_binding"]
        binding.pop("inactive_candidates")
        return stripped

    def test_plugin_ultrawork_uses_active_gpt_model_overlay(self) -> None:
        import os
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch

        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.dict(os.environ, {"OMH_HOME": str(root / ".omh"), "HERMES_HOME": str(root / ".hermes")}):
                interaction = self._plugin_ulw_interaction(root, model="gpt-5.6-sol")

        self.assertEqual(interaction["route"]["selected_skill"], "ultrawork")
        overlay = interaction["delegation"]["runtime_handoff"]["executor_prompting_contract"]["throughput_overlay"]
        self.assertEqual(overlay["mode"], "gpt_hermes_ulw")
        self.assertEqual(
            interaction["delegation"]["runtime_handoff"]["hermes_native_model_binding"][
                "inactive_candidates"
            ],
            ["gpt-6.2-sol", "claude-opus-5-5", "kimi-k3.1-pro"],
        )
        self.assertNotIn(
            "gpt-5.6-sol",
            json.dumps(self._without_catalog_candidates(interaction), sort_keys=True),
        )

    def test_plugin_ultraprocess_uses_active_gpt_model_overlay(self) -> None:
        import os
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch

        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.dict(os.environ, {"OMH_HOME": str(root / ".omh"), "HERMES_HOME": str(root / ".hermes")}):
                interaction = self._plugin_ulw_interaction(
                    root,
                    model="gpt-5.6-sol",
                    workflow="ultrawork",
                )

        self.assertEqual(interaction["route"]["selected_skill"], "ultrawork")
        overlay = interaction["delegation"]["runtime_handoff"]["executor_prompting_contract"]["throughput_overlay"]
        self.assertEqual(overlay["mode"], "gpt_hermes_ulw")

    def test_plugin_model_context_resets_between_messenger_turns(self) -> None:
        import os
        from pathlib import Path
        from tempfile import TemporaryDirectory
        from unittest.mock import patch

        with TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            with patch.dict(os.environ, {"OMH_HOME": str(root / ".omh"), "HERMES_HOME": str(root / ".hermes")}):
                gpt_interaction = self._plugin_ulw_interaction(root, model="gpt-5.6-sol")
                claude_interaction = self._plugin_ulw_interaction(root, model="claude-sonnet-4-5")
                empty_interaction = self._plugin_ulw_interaction(root, model="")

        gpt_overlay = gpt_interaction["delegation"]["runtime_handoff"]["executor_prompting_contract"][
            "throughput_overlay"
        ]
        claude_overlay = claude_interaction["delegation"]["runtime_handoff"]["executor_prompting_contract"][
            "throughput_overlay"
        ]
        empty_overlay = empty_interaction["delegation"]["runtime_handoff"]["executor_prompting_contract"][
            "throughput_overlay"
        ]
        self.assertEqual(gpt_overlay["mode"], "gpt_hermes_ulw")
        self.assertEqual(claude_overlay["mode"], "parallel_handoff")
        self.assertEqual(empty_overlay["mode"], "parallel_handoff")
        self.assertNotIn("eval_strategy", claude_overlay)
        self.assertNotIn("eval_strategy", empty_overlay)
        expected_inactive = ["gpt-6.2-sol", "claude-opus-5-5", "kimi-k3.1-pro"]
        for interaction in (gpt_interaction, claude_interaction, empty_interaction):
            self.assertEqual(
                interaction["delegation"]["runtime_handoff"]["hermes_native_model_binding"][
                    "inactive_candidates"
                ],
                expected_inactive,
            )
        serialized = json.dumps(
            [
                self._without_catalog_candidates(gpt_interaction),
                self._without_catalog_candidates(claude_interaction),
                self._without_catalog_candidates(empty_interaction),
            ],
            sort_keys=True,
        )
        self.assertNotIn("gpt-5.6-sol", serialized)
        self.assertNotIn("claude-sonnet-4-5", serialized)


if __name__ == "__main__":
    unittest.main()
