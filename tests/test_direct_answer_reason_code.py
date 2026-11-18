"""A route that says "answer directly" gets a direct-answer card, chosen by its reason code.

The router names each answer-in-chat fallback with a stable `reason_code`
beside the prose `reason`. Every surface that branches on the kind of fallback
reads the code: the prose is for a reader and may be reworded, and the compact
`route_decision` contract truncates it to thirteen characters, which is why
the route-hint card could not tell a thank-you from an unmatched request and
showed both the generic "Open omh" / "Clarify" card.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from _cli_harness import run_cli
from _local_package import load_local_package

load_local_package()

from omh.quality.routing_precision import ROUTING_INTERVENTION_CASES, ROUTING_PRECISION_CASES
from omh.routing import chat
from omh.routing.chat import (
    CODE_BACKLOG_REASON,
    DIRECT_ANSWER_REASON,
    DIRECT_ANSWER_REASON_CODES,
    FILE_LOOKUP_REASON,
    HOST_COMMAND_TURN_REASON,
    LOOP_CONSTRUCT_REASON,
    LOOP_TIMER_ANSWER_REASON_CODES,
    NATIVE_LOOP_CADENCE_REASON,
    REASON_CODE_FILE_LOOKUP,
    TYPED_LOOP_GOAL_REASON,
    route_chat_message,
    route_explanation_payload,
)
from omh.wrapper import contract
from omh.wrapper.native_commands import render_native_command_response
from omh.wrapper.route_hints import build_chat_route_hint_payload

# Each code beside the prose it names, written out here rather than read from
# the module, so a code moved onto the wrong prose fails below.
_PROSE_BY_CODE = {
    "file_lookup": FILE_LOOKUP_REASON,
    "direct_answer": DIRECT_ANSWER_REASON,
    "host_command_turn": HOST_COMMAND_TURN_REASON,
    "native_loop_cadence": NATIVE_LOOP_CADENCE_REASON,
    "typed_loop_goal": TYPED_LOOP_GOAL_REASON,
    "loop_construct": LOOP_CONSTRUCT_REASON,
    "code_backlog": CODE_BACKLOG_REASON,
}
_CODE_BY_PROSE = {prose: code for code, prose in _PROSE_BY_CODE.items()}

_PLAN_TURN = "[/plan — plan mode]\nFor this turn, you are in PLAN MODE. Plan the database migration."
_PLAN_FRAME = "[/plan — plan mode]\nFor this turn, you are in PLAN MODE\n\n"
_HEARTBEAT_FRAME = "[Heartbeat — recurring instruction, fires every 5m]\n"
_LEARN_FRAME = (
    "[/learn] The user wants you to learn a reusable skill from the request below, and save it.\nTHE REQUEST:\n"
)
_DIRECT_ANSWER_BOUNDARY = "No OMH workflow, picker, handoff, execution, or file inspection has started."
_REWORDED = "Reworded for a reader; nothing here is a phrase any predicate knows."


def _precision_message(case_id: str) -> str:
    return {case.id: case for case in ROUTING_PRECISION_CASES}[case_id].message


class ReasonCodeContractTest(unittest.TestCase):
    def test_the_code_sets_are_the_named_codes(self) -> None:
        self.assertEqual(
            DIRECT_ANSWER_REASON_CODES,
            {"direct_answer", "host_command_turn", "native_loop_cadence", "typed_loop_goal", "loop_construct", "code_backlog"},
        )
        self.assertEqual(LOOP_TIMER_ANSWER_REASON_CODES, {"native_loop_cadence", "typed_loop_goal", "loop_construct"})
        self.assertEqual(REASON_CODE_FILE_LOOKUP, "file_lookup")

    def test_every_corpus_route_carries_the_code_of_its_reason_and_no_other(self) -> None:
        # Both routing corpora: a route carries a code exactly when its reason
        # is one of the coded fallbacks, and the compact contract carries the
        # same one. A later step that rewrites the reason and keeps the code
        # (or sets the prose without the code) fails here.
        seen: set[str] = set()
        for case in (*ROUTING_PRECISION_CASES, *ROUTING_INTERVENTION_CASES):
            route = route_chat_message(case.message, source="discord")
            expected = _CODE_BY_PROSE.get(str(route["reason"]), "")
            with self.subTest(case=case.id):
                self.assertEqual(route.get("reason_code", ""), expected)
                self.assertEqual(route["route_decision"].get("reason_code", ""), expected)
                if expected:
                    self.assertEqual(route["action"], "fallback")
            seen.add(expected)
        # Each code is exercised by at least one corpus case.
        self.assertEqual(seen - {""}, set(_PROSE_BY_CODE))

    def test_a_learning_card_that_replaces_a_direct_answer_drops_its_code(self) -> None:
        # The scorer first reads this as a plain question; the learning
        # signal then turns it into a dispatch with its own reason, and the
        # direct-answer code must go with the reason it named.
        route = chat.public_chat_route_payload("next time just answer: what is a closure in python?", source="discord")
        self.assertEqual(route["action"], "dispatch")
        self.assertNotIn("reason_code", route)
        self.assertNotIn("reason_code", route["route_decision"])
        self.assertNotEqual(
            route["route_explanation"]["claim_boundary"],
            "No OMH workflow, picker, handoff, execution, or file inspection has started.",
        )

    def test_a_route_with_no_code_carries_no_key(self) -> None:
        route = route_chat_message("make an image explaining the cron feature", source="discord")
        self.assertEqual(route["action"], "dispatch")
        self.assertNotIn("reason_code", route)
        self.assertNotIn("reason_code", route["route_decision"])


class PredicatesReadTheCodeTest(unittest.TestCase):
    """Each pair differs only in which of the two fields says direct answer."""

    @staticmethod
    def _route(*, reason: str, reason_code: str = "") -> dict[str, object]:
        route: dict[str, object] = {
            "action": "fallback",
            "selected_skill": "oh-my-hermes",
            "candidate_skill": "oh-my-hermes",
            "reason": reason,
            "clarification": "",
            "routing_instruction": "",
            "recommendations": [],
        }
        if reason_code:
            route["reason_code"] = reason_code
            route["route_decision"] = {"schema_version": "route_decision/v1", "reason_code": reason_code}
        return route

    def test_the_router_explanation_reads_the_code(self) -> None:
        coded = route_explanation_payload(self._route(reason=_REWORDED, reason_code="host_command_turn"))
        prose_only = route_explanation_payload(self._route(reason=HOST_COMMAND_TURN_REASON))
        self.assertEqual(coded["next_action"], "answer_directly")
        self.assertNotEqual(prose_only["next_action"], "answer_directly")
        self.assertEqual(coded["claim_boundary"], _DIRECT_ANSWER_BOUNDARY)
        self.assertNotEqual(prose_only["claim_boundary"], _DIRECT_ANSWER_BOUNDARY)
        lookup = route_explanation_payload(self._route(reason=_REWORDED, reason_code="file_lookup"))
        lookup_prose_only = route_explanation_payload(self._route(reason=FILE_LOOKUP_REASON))
        self.assertEqual(lookup["next_action"], "answer_file_lookup")
        self.assertNotEqual(lookup_prose_only["next_action"], "answer_file_lookup")
        lookup_boundary = "No OMH workflow, execution, or file inspection has started."
        self.assertEqual(lookup["claim_boundary"], lookup_boundary)
        self.assertNotEqual(lookup_prose_only["claim_boundary"], lookup_boundary)

    def test_the_clarification_reads_the_code(self) -> None:
        # The router writes `clarification` while it builds the decision, so
        # the pair is the builder's own call with and without the code.
        direct = "Answer directly in the current chat; do not open an OMH workflow unless the user asks for one."
        lookup = "Answer this as a file or text lookup, or ask for the target file/path if it is missing."
        for code, prose, expected in (
            ("direct_answer", DIRECT_ANSWER_REASON, direct),
            ("host_command_turn", HOST_COMMAND_TURN_REASON, direct),
            ("file_lookup", FILE_LOOKUP_REASON, lookup),
        ):
            with self.subTest(code=code):
                coded = chat._clarification("fallback", "oh-my-hermes", "low", "high", _REWORDED, reason_code=code)
                prose_only = chat._clarification("fallback", "oh-my-hermes", "low", "high", prose)
                self.assertEqual(coded, expected)
                self.assertNotEqual(prose_only, expected)
        # The routed decision carries the coded sentence.
        self.assertEqual(route_chat_message("thanks!", source="discord")["clarification"], direct)

    def test_the_routing_instruction_reads_the_code(self) -> None:
        coded = chat.public_route_payload(self._route(reason=_REWORDED, reason_code="direct_answer"))
        prose_only = chat.public_route_payload(self._route(reason=DIRECT_ANSWER_REASON))
        self.assertTrue(coded["routing_instruction"].startswith("Answer directly in chat"))
        self.assertFalse(prose_only["routing_instruction"].startswith("Answer directly in chat"))

    def test_the_wrapper_predicates_read_the_code(self) -> None:
        for code in DIRECT_ANSWER_REASON_CODES:
            with self.subTest(code=code):
                self.assertTrue(contract._is_direct_answer_fallback(self._route(reason=_REWORDED, reason_code=code)))
                self.assertFalse(contract._is_direct_answer_fallback(self._route(reason=_PROSE_BY_CODE[code])))
        for code in LOOP_TIMER_ANSWER_REASON_CODES:
            with self.subTest(code=code):
                self.assertTrue(contract._is_loop_timer_answer(self._route(reason=_REWORDED, reason_code=code)))
                self.assertFalse(contract._is_loop_timer_answer(self._route(reason=_PROSE_BY_CODE[code])))
        self.assertFalse(contract._is_loop_timer_answer(self._route(reason=_REWORDED, reason_code="direct_answer")))
        self.assertTrue(contract._is_file_lookup_fallback(self._route(reason=_REWORDED, reason_code="file_lookup")))
        self.assertFalse(contract._is_file_lookup_fallback(self._route(reason=FILE_LOOKUP_REASON)))

    def test_a_route_the_wrapper_turns_into_an_omh_card_drops_the_old_code(self) -> None:
        # These four replace the reason with their own; a code left behind
        # would name the reason they replaced (the explanation would then say
        # no workflow has started beside a dispatch).
        for build in (
            contract._catalog_question_route_payload,
            contract._omh_status_route_payload,
            contract._omh_quickstart_route_payload,
            contract._omh_intro_route_payload,
        ):
            with self.subTest(build=build.__name__):
                route = self._route(reason=DIRECT_ANSWER_REASON, reason_code="direct_answer")
                updated = build(route)
                self.assertEqual(updated["action"], "dispatch")
                self.assertNotIn("reason_code", updated)
                self.assertNotIn("reason_code", updated["route_decision"])
                self.assertNotEqual(updated["route_explanation"]["claim_boundary"], _DIRECT_ANSWER_BOUNDARY)
                # A copy: the route it was built from keeps its code.
                self.assertEqual(route["route_decision"]["reason_code"], "direct_answer")

    def test_a_host_turn_never_becomes_an_omh_intro_quickstart_or_status_card(self) -> None:
        # A session-command turn whose body asks about OMH is still Hermes'
        # instruction for itself: the interaction answers it directly, and the
        # route and its compact contract name the same code.
        for frame in (_PLAN_FRAME, _HEARTBEAT_FRAME, _LEARN_FRAME):
            for body, typed_kind in (
                ("omh status", "status"),
                ("omh quickstart", "quickstart"),
                ("how do I use omh?", "context_brief"),
            ):
                with self.subTest(frame=frame.split("]")[0], body=body):
                    payload = contract.build_chat_interaction_payload(frame + body, source="discord")
                    route = payload["route"]
                    self.assertEqual(payload["chat_response"]["kind"], "clarification")
                    self.assertEqual(payload["chat_response"]["state"]["lookup_kind"], "direct_answer")
                    self.assertEqual(route["action"], "fallback")
                    self.assertEqual(route["reason_code"], "host_command_turn")
                    self.assertEqual(route["route_decision"]["reason_code"], "host_command_turn")
                    # The same body typed by a person still gets its OMH card.
                    typed = contract.build_chat_interaction_payload(body, source="discord")
                    self.assertEqual(typed["chat_response"]["kind"], typed_kind)
                    self.assertNotIn("reason_code", typed["route"])
                    self.assertNotIn("reason_code", typed["route"]["route_decision"])


class DirectAnswerRouteHintCardTest(unittest.TestCase):
    def _assert_direct_answer_card(self, payload: dict[str, object], code: str) -> None:
        response = payload["chat_response"]
        self.assertEqual(payload["route_decision"]["action"], "fallback")
        self.assertEqual(payload["route_decision"]["reason_code"], code)
        self.assertEqual(response["kind"], "direct_answer_route_hint")
        self.assertEqual(response["actions"], [])
        self.assertEqual(response["headline"], "[omh] no workflow needed.")
        self.assertIn("no OMH workflow", response["body"])
        self.assertNotIn("Checkpoint:", response["body"])
        self.assertEqual(response["messenger_rendering"]["checkpoint_text"], "")
        self.assertIsNone(response["messenger_rendering"]["primary_action"])
        self.assertEqual(response["messenger_rendering"]["secondary_actions"], [])
        self.assertEqual(response["state"]["selected_workflow"], "")
        self.assertEqual(response["state"]["next_action"], "answer_directly")
        self.assertEqual(response["visible_prefix"], "[omh] hint:none")

    def test_a_thank_you_a_host_turn_and_a_loop_on_a_timer_get_the_direct_answer_card(self) -> None:
        for message, code in (
            ("thanks!", "direct_answer"),
            ("[alice] thanks!", "direct_answer"),
            (_PLAN_TURN, "host_command_turn"),
            ("/loop 5m check CI", "native_loop_cadence"),
        ):
            for source in ("discord", "slack", "telegram", "generic"):
                with self.subTest(message=message, source=source):
                    self._assert_direct_answer_card(build_chat_route_hint_payload(message, source=source), code)

    def test_the_route_decides_the_card_over_a_hint_that_named_a_workflow(self) -> None:
        # The router answers "how long does it take to become a doctor"
        # directly; the hint rail matched the word `doctor`. The card follows
        # the route, and the hint stays in `route_hint` for a reader.
        payload = build_chat_route_hint_payload(_precision_message("become-a-doctor-is-not-doctor"), source="discord")
        self._assert_direct_answer_card(payload, "direct_answer")
        self.assertEqual(payload["route_hint"]["primary_workflow"], "doctor")

    def test_the_backend_commands_offer_no_hinted_workflow_on_a_direct_answer(self) -> None:
        payload = build_chat_route_hint_payload(_precision_message("become-a-doctor-is-not-doctor"), source="discord")
        commands = payload["wrapper_contract"]["next_backend_commands"]
        self.assertEqual([command["id"] for command in commands], ["route_for_me", "open_picker"])
        self.assertNotIn("./doctor", " ".join(command["command"] for command in commands))
        # A routed request still leads with its workflow.
        routed = build_chat_route_hint_payload("make an image explaining the cron feature", source="discord")
        self.assertEqual(routed["wrapper_contract"]["next_backend_commands"][0]["id"], "open_workflow")

    def test_the_human_summary_reads_the_card(self) -> None:
        message = _precision_message("become-a-doctor-is-not-doctor")
        status, stdout, stderr = run_cli(["chat", "route-hint", "--source", "discord", message], output_json=False)
        self.assertEqual((status, stderr), (0, ""))
        self.assertIn("Status: direct_answer\nWorkflow: none\nNext action: answering directly in chat\nHints: 0", stdout)
        self.assertIn("[omh] no workflow needed.", stdout)
        for absent in ("doctor", "Checkpoint:", "Hint details:", "Matched cues:"):
            self.assertNotIn(absent, stdout)
        # The JSON still carries the hint the card set aside.
        status, stdout, _ = run_cli(["chat", "route-hint", "--source", "discord", "--json", message], output_json=False)
        self.assertEqual(status, 0)
        self.assertEqual(json.loads(stdout)["route_hint"]["primary_workflow"], "doctor")

    def test_other_fallbacks_and_routed_requests_keep_their_cards(self) -> None:
        unmatched = build_chat_route_hint_payload("zzzzzz", source="slack")
        self.assertEqual(unmatched["route_decision"]["action"], "fallback")
        self.assertNotIn("reason_code", unmatched["route_decision"])
        self.assertEqual(unmatched["chat_response"]["kind"], "no_route_hint")
        self.assertEqual([a["id"] for a in unmatched["chat_response"]["actions"]], ["open_picker", "clarify"])

        # A file lookup is answered in chat too, but with its own next action;
        # it is not a direct-answer card.
        lookup = build_chat_route_hint_payload(_precision_message("repo-file-list"), source="discord")
        self.assertEqual(lookup["route_decision"]["reason_code"], "file_lookup")
        self.assertEqual(lookup["chat_response"]["kind"], "no_route_hint")

        routed = build_chat_route_hint_payload("make an image explaining the cron feature", source="discord")
        self.assertEqual(routed["chat_response"]["kind"], "workflow_route_hint")

    def test_the_interaction_card_is_the_direct_answer_clarification_it_was(self) -> None:
        for message in ("thanks!", _PLAN_TURN, "/loop 5m check CI"):
            with self.subTest(message=message):
                payload = contract.build_chat_interaction_payload(message, source="discord")
                self.assertEqual(payload["chat_response"]["kind"], "clarification")
                self.assertEqual(payload["chat_response"]["state"]["lookup_kind"], "direct_answer")
                self.assertEqual(payload["next_action"], "answer_directly")


class CardKindsDegradeSafelyTest(unittest.TestCase):
    """The shims and the platform renderers render any card kind, known or not."""

    def setUp(self) -> None:
        examples_dir = str(Path(__file__).resolve().parents[1] / "examples")
        if examples_dir not in sys.path:
            sys.path.insert(0, examples_dir)
            self.addCleanup(sys.path.remove, examples_dir)
        import wrapper_shim_common

        self.shim = wrapper_shim_common

    def _payloads(self, source: str) -> list[dict[str, object]]:
        direct = build_chat_route_hint_payload("thanks!", source=source)
        unknown = build_chat_route_hint_payload("thanks!", source=source)
        unknown["chat_response"] = {**unknown["chat_response"], "kind": "a_kind_added_later"}
        return [direct, unknown]

    def test_the_shims_render_the_card_without_actions(self) -> None:
        for source in ("discord", "slack", "telegram"):
            for payload in self._payloads(source):
                kind = payload["chat_response"]["kind"]
                with self.subTest(source=source, kind=kind):
                    rendered = self.shim._render_route_hint(source, payload)
                    self.assertEqual(rendered["response"]["kind"], kind)
                    self.assertEqual(rendered["response"]["headline"], "[omh] no workflow needed.")
                    self.assertEqual(rendered["actions"], [])
                    self.assertEqual(rendered["next_action"], "answer_directly")
                    self.assertEqual(rendered["usage_trace"]["visible_prefix"], "[omh] route_hint")

    def test_the_platform_renderers_fall_back_to_a_plain_chat_card(self) -> None:
        for source in ("discord", "slack", "telegram"):
            for payload in self._payloads(source):
                kind = payload["chat_response"]["kind"]
                with self.subTest(source=source, kind=kind):
                    rendered = render_native_command_response(payload, source=source)
                    self.assertEqual(rendered["response_kind"], kind)
                    self.assertEqual(rendered["render_kind"], "chat_response")
                    self.assertEqual(rendered["headline"], "[omh] no workflow needed.")
                    self.assertEqual(rendered["actions"], [])
                    self.assertEqual(rendered["render_warnings"], [])


if __name__ == "__main__":
    unittest.main()
