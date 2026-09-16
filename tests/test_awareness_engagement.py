"""Whether OMH engages at all: vocabulary reach, the todo ask, and the first turn.

Three independent reasons a live session saw nothing while every routing test
stayed green. All three sit in the plugin bundle -- the copy that actually runs
in a session -- while the repo's routing corpora measure `src/routing/`.

* A bare `ulw`, the router's own abbreviation for `ultrawork`, was a clean
  explicit dispatch on `public_chat_route_payload` and a zero-length context
  from `awareness_route_hint`. So were the historical `omh-loop` and
  `omh-research` labels.
* A hint that did fire named the workflow, the lane, the next action and the
  first-response shape, and said nothing about declaring a checklist -- for the
  workflows whose run IS a checklist. The per-turn plan line could not cover
  it: it reads an `established` plan, so it continues a checklist and never
  starts one.
* The block that says OMH exists was gated on the user's message already
  containing OMH vocabulary, so six of eight ordinary work requests got
  nothing -- including "migrate the database schema, update all models, fix the
  tests, and write the migration guide", which is plainly multi-lane work.

Each fix ships its negative case beside its positive one, because each fix
widens a surface that overrouting is the standing risk on.
"""

from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory

from _local_package import load_local_package

load_local_package()
from omh.plugin_bundle.omh import awareness as awareness_module
from omh.plugin_bundle.omh.awareness import (
    awareness_primer_context,
    awareness_route_hint,
    awareness_route_hint_context,
    workflow_declares_plan_todo,
)
from omh.plugin_bundle.omh.awareness_delivery import read_awareness_delivery
from omh.plugin_bundle.omh.hooks.llm_hooks import pre_llm_call
from omh.routing.chat import public_chat_route_payload


def _hinted_workflow(message: str) -> str:
    hints = awareness_route_hint(message).get("hints") or []
    return str(hints[0].get("workflow", "")) if hints else ""


# Ordinary work requests carrying no OMH word, measured as misses before the
# first-turn change. The sixth is the one that makes the case: naming six
# surfaces in one sentence is exactly the shape a task-size heuristic would
# claim to catch, and it was a miss.
ORDINARY_WORK_REQUESTS = (
    "add a retry to the upload handler",
    "fix the failing test in test_cli.py",
    "refactor the auth module and update the callers",
    "build a REST API for the user service with tests and docs",
    "this whole payment flow is broken, find out why and fix it end to end",
    "migrate the database schema, update all models, fix the tests, and write the migration guide",
    "로그인 버그 고쳐줘",
    "implement dark mode across the settings screens",
)


class BundleReachesEveryRouterSpellingTests(unittest.TestCase):
    """A spelling the router dispatches must reach the live hint surface too."""

    def test_the_spellings_that_missed_now_hint_their_canonical_workflow(self) -> None:
        for alias, canonical in (
            ("ulw", "ultrawork"),
            ("omh-loop", "loop"),
            ("omh-research", "research"),
        ):
            with self.subTest(alias=alias):
                canonical_hint = _hinted_workflow(f"{canonical} the auth refactor")
                self.assertTrue(canonical_hint, canonical)
                self.assertEqual(_hinted_workflow(f"{alias} the auth refactor"), canonical_hint)
                # The router side of the same message, so the comparison is
                # against what a live session's routing actually decided.
                route = public_chat_route_payload(f"{alias} the auth refactor")
                self.assertEqual(route["selected_skill"], canonical)

    def test_an_alias_is_invocable_the_ways_the_router_accepts(self) -> None:
        for message in ("ulw the auth refactor", "use ulw on the auth refactor", "run ulw on the api"):
            with self.subTest(message=message):
                self.assertEqual(_hinted_workflow(message), "ulw-work")

    def test_a_word_that_merely_contains_an_alias_is_not_an_invocation(self) -> None:
        """The negative half. `ulw` is three letters, so substring reach is the risk.

        `ulw-nonexistent` is in here for the other boundary: a hyphen IS a word
        boundary, so a plain `\\b` would have resolved an invented label to
        `ultrawork` while the router, whose alias lookup is keyed on the whole
        token, reads it as no explicit invocation at all.
        """
        for message in (
            "ulwork the refactor",
            "sulw the thing",
            "ulw_work the refactor",
            "ulw-nonexistent the thing",
            "culwort grows by the river",
        ):
            with self.subTest(message=message):
                self.assertEqual(awareness_route_hint(message).get("hints"), [])

    def test_an_alias_is_no_more_an_invocation_than_the_name_it_stands_for(self) -> None:
        """A fused particle empties both forms out, so the router's vagueness gate wins.

        `ulw로 이거 해줘` names no target. The router answers it with a clarify;
        this module must not hint past that, and it must treat the alias and
        the full name identically rather than opening a second behavior.
        """
        for message in ("ulw로 이거 해줘", "ultrawork로 이거 해줘"):
            with self.subTest(message=message):
                self.assertEqual(awareness_route_hint(message).get("hints"), [])
                self.assertEqual(public_chat_route_payload(message)["action"], "clarify")


class RouteHintPlanTodoTests(unittest.TestCase):
    """A hint for a checklist-walking run says to declare the checklist."""

    def test_a_workflow_that_walks_a_checklist_is_told_to_declare_one(self) -> None:
        for message, workflow in (
            ("ultrawork on the auth refactor", "ulw-work"),
            ("ultraqa the module", "ulw-qa"),
            ("loop on the flaky test", "ulw-loop"),
            ("ralplan the migration", "ulw-plan"),
        ):
            with self.subTest(message=message):
                context = awareness_route_hint_context(message)
                self.assertEqual(_hinted_workflow(message), workflow)
                self.assertIn("plan_todo=", context)
                self.assertIn("omh_todo", context)
                self.assertIn("declarations, never execution evidence", context)

    def test_a_one_card_or_one_answer_workflow_is_not(self) -> None:
        """The negative half: `ulw-context` and `ulw-interview` are engines too.

        Both are in the engine set, so a comprehension over that set would have
        added the line here as well. A route that produces one card or asks one
        question has nothing to put on a checklist.
        """
        for message, workflow in (
            ("context the repo", "ulw-context"),
            ("deep-interview the goal", "ulw-interview"),
            ("code-review the diff", "code-review"),
        ):
            with self.subTest(message=message):
                self.assertEqual(_hinted_workflow(message), workflow)
                self.assertNotIn("plan_todo=", awareness_route_hint_context(message))

    def test_the_predicate_reads_the_emitted_name_and_the_catalog_key(self) -> None:
        # The hint is rendered after the public-name projection, so the string
        # that reaches the predicate is `ulw-work`, never `ultrawork`.
        self.assertTrue(workflow_declares_plan_todo("ulw-work"))
        self.assertTrue(workflow_declares_plan_todo("ultrawork"))
        self.assertFalse(workflow_declares_plan_todo("ulw-context"))
        self.assertFalse(workflow_declares_plan_todo(""))

    def test_every_plan_todo_workflow_is_one_this_module_can_emit(self) -> None:
        """No dead rows: a renamed or dropped workflow must not sit here unnoticed."""
        emittable = set(awareness_module._WORKFLOW_CONTEXT_CARD_BY_WORKFLOW) | set(
            awareness_module._DIRECT_WORKFLOW_NEXT_ACTIONS
        )
        self.assertTrue(awareness_module._PLAN_TODO_WORKFLOWS)
        self.assertEqual(awareness_module._PLAN_TODO_WORKFLOWS - emittable, set())


class FirstTurnCarriesAwarenessTests(unittest.TestCase):
    """The session's first turn says OMH exists without being asked in OMH's words."""

    def test_a_first_turn_with_no_omh_vocabulary_still_gets_the_primer(self) -> None:
        with TemporaryDirectory() as omh_home:
            for index, message in enumerate(ORDINARY_WORK_REQUESTS):
                with self.subTest(message=message):
                    result = pre_llm_call(
                        user_message=message,
                        is_first_turn=True,
                        session_id=f"session-{index}",
                        omh_home=omh_home,
                    )
                    self.assertIsNotNone(result)
                    assert result is not None
                    self.assertIn("[OMH Awareness]", result["context"])

    def test_a_later_turn_with_no_omh_vocabulary_still_gets_nothing(self) -> None:
        """The gate is unchanged off the first turn; only the first turn is free.

        One of the eight does match the matcher on its own, so it is excluded
        here rather than asserted into a miss it never had.
        """
        with TemporaryDirectory() as omh_home:
            for index, message in enumerate(ORDINARY_WORK_REQUESTS):
                if awareness_module.awareness_context_matches_message(message):
                    continue
                with self.subTest(message=message):
                    self.assertIsNone(
                        pre_llm_call(
                            user_message=message,
                            is_first_turn=False,
                            session_id=f"later-{index}",
                            omh_home=omh_home,
                        )
                    )

    def test_the_primer_is_not_repeated_once_it_is_in_the_history(self) -> None:
        primer = awareness_primer_context()
        with TemporaryDirectory() as omh_home:
            result = pre_llm_call(
                user_message="add a retry to the upload handler",
                conversation_history=[
                    {
                        "role": "user",
                        "content": "add a retry to the upload handler",
                        "api_content": "add a retry to the upload handler\n\n" + primer,
                    }
                ],
                is_first_turn=True,
                session_id="session-repeat",
                omh_home=omh_home,
            )

            self.assertIsNone(result)

    def test_route_guidance_fingerprint_suppression_still_holds(self) -> None:
        """Widening the primer must not let the same route guidance go out twice."""
        message = "ultrawork on the auth refactor"
        with TemporaryDirectory() as omh_home:
            first = pre_llm_call(
                user_message=message,
                is_first_turn=True,
                session_id="session-fingerprint",
                omh_home=omh_home,
            )
            second = pre_llm_call(
                user_message=message,
                is_first_turn=True,
                session_id="session-fingerprint",
                omh_home=omh_home,
            )

            self.assertIsNotNone(first)
            assert first is not None
            self.assertIn("[OMH Route Hint]", first["context"])
            self.assertIn("plan_todo=", first["context"])

            self.assertIsNotNone(second)
            assert second is not None
            self.assertNotIn("[OMH Route Hint]", second["context"])

            # The ledger side of the same claim. `suppressed_count` is the
            # wrong field to read here -- it counts turns the hook answered
            # with nothing at all, and the second turn still carries a primer.
            # `route_hint_count` is what the fingerprint claim gates.
            delivery = read_awareness_delivery(omh_home)
            self.assertEqual(delivery["delivery_count"], 2)
            self.assertEqual(delivery["route_hint_count"], 1)


if __name__ == "__main__":
    unittest.main()
