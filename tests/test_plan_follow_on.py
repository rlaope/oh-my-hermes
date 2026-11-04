"""`dag-ulw` is offered on `/plan`'s turn and on the turn that accepts a plan just made, and nowhere else.

A turn with no fresh plan must render exactly what it rendered before, so the
negative cases assert absence, and the byte-identity case compares the whole
context with the follow-on reader switched off.
"""
from __future__ import annotations

import json
import unittest
from functools import cached_property
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from _cli_harness import run_cli
from omh.plugin_bundle.omh import plan_follow_on
from omh.plugin_bundle.omh.active_workflow_context_state import ALLOWED_TRANSITIONS
from omh.plugin_bundle.omh.hooks import llm_hooks
from omh.plugin_bundle.omh.skill_shortlist import reset_candidate_line_state
from omh.plugin_bundle.omh.plan_follow_on import (
    ACCEPTANCE_LINE,
    PLAN_TURN_LINE,
    accepts_plan,
    acceptance_line,
    plan_just_made,
    plan_turn_line,
)

PLAN_TURN = (
    "[/plan — plan mode]\n\nFor this turn, you are in PLAN MODE — planning only.\n\n"
    "- Do not implement code.\n\nTask to plan:\nadd CSV export to the reports page\n"
)
PLAN_REPLY = "Saved the plan to .hermes/plans/2026-11-04_101500-export.md (T1-T5). Want me to carry it out?"
# The six acceptance messages the owner's path produced.
ACCEPTANCES = (
    "좋아 이 플랜대로 구현해줘",
    "구현하기",
    "accepted, carry it out",
    "looks good, implement the plan",
    "Yes, execute the plan in .hermes/plans/2026-11-04_101500-export.md",
    "플랜 승인. 진행해",
)
MORE_ACCEPTANCES = (
    "go ahead",
    "ok, start",
    "approved",
    "좋아요 시작해 주세요",
    "ㅇㅋ 진행",
    "네 그대로 만들어주세요",
    "Plan approved — begin implementing.",
    "sure, do it",
)
# Read right after a plan, none of these says go with the way to run it open.
NOT_ACCEPTANCES = (
    "T3을 Redis로 바꿔줘",
    "what does T4 test?",
    "hold on, I need to check with the team",
    "run it with dag-ulw",
    "ultrawork로 진행해",
    "직접 구현해",
    "no, rewrite the plan around the queue",
    "Before you start, add a lint step",
    "좋아 근데 T2는 빼고",
    "구현 전에 리스크 설명해줘",
    "implement it with subagents",
    "왜 T5가 마지막이야",
    "구현은 T1부터 시작하는 거지?",
    "ok I will read the whole plan tonight with my coworkers and we can talk about it tomorrow morning",
    "",
)


def hermes_history(message: str) -> list[dict[str, object]]:
    return [
        {"role": "user", "content": PLAN_TURN},
        {"role": "assistant", "content": PLAN_REPLY},
        {"role": "user", "content": message},
    ]


class AcceptsPlanTests(unittest.TestCase):
    def test_acceptances_say_go(self) -> None:
        for message in ACCEPTANCES + MORE_ACCEPTANCES:
            with self.subTest(message=message):
                self.assertTrue(accepts_plan(message))

    def test_changes_questions_holds_and_chosen_paths_do_not(self) -> None:
        for message in NOT_ACCEPTANCES:
            with self.subTest(message=message):
                self.assertFalse(accepts_plan(message))


class PlanJustMadeTests(unittest.TestCase):
    def test_hermes_plan_turn_before_this_one(self) -> None:
        self.assertTrue(plan_just_made(hermes_history("구현하기")))

    def test_gateway_sender_prefix_before_the_plan_frame(self) -> None:
        # The reply names no plan file, so only the frame can say a plan was made.
        history = [{"role": "user", "content": "[alice] " + PLAN_TURN},
                   {"role": "assistant", "content": "Planned it. Want me to carry it out?"},
                   {"role": "user", "content": "구현하기"}]
        self.assertTrue(plan_just_made(history))
        self.assertEqual(plan_turn_line("[alice] " + PLAN_TURN), PLAN_TURN_LINE)

    def test_plan_file_written_by_a_tool_call(self) -> None:
        arguments = json.dumps({"path": ".hermes/plans/2026-11-04_101500-export.md", "content": "# Plan"})
        history = [
            {"role": "user", "content": "change T3 to use the queue"},
            {"role": "assistant", "content": "",
             "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "write_file", "arguments": arguments}}]},
            {"role": "tool", "tool_call_id": "c1", "content": "ok"},
            {"role": "assistant", "content": "Updated T3."},
            {"role": "user", "content": "좋아 진행해"},
        ]
        self.assertTrue(plan_just_made(history))

    def test_planning_skill_loaded_the_turn_before(self) -> None:
        for name in ("omh-plan", "ulw-plan", "planning/omh-refactor-plan"):
            with self.subTest(name=name):
                history = [
                    {"role": "user", "content": "plan the CSV export"},
                    {"role": "assistant", "content": "",
                     "tool_calls": [{"function": {"name": "skill_view", "arguments": json.dumps({"name": name})}}]},
                    {"role": "assistant", "content": "T1 schema, T2 writer, T3 verify. Accept?"},
                    {"role": "user", "content": "구현하기"},
                ]
                self.assertTrue(plan_just_made(history))

    def test_planning_skill_invoked_by_slash(self) -> None:
        frame = (
            '[IMPORTANT: The user has invoked the "omh-plan" skill, indicating they want you to follow its '
            "instructions. The full skill content is loaded below.]\n\n# Plan\n\n"
            "The user has provided the following instruction alongside the skill invocation: plan CSV export"
        )
        history = [{"role": "user", "content": frame}, {"role": "assistant", "content": "T1..T4"},
                   {"role": "user", "content": "ok go ahead"}]
        self.assertTrue(plan_just_made(history))

    def test_no_plan_before_this_turn(self) -> None:
        unrelated_skill = [{"function": {"name": "skill_view", "arguments": json.dumps({"name": "code-review"})}}]
        histories = {
            "none": None,
            "only this turn": [{"role": "user", "content": "구현하기"}],
            "other chat": [
                {"role": "user", "content": "what's in the reports page?"},
                {"role": "assistant", "content": "It lists monthly totals."},
                {"role": "user", "content": "구현하기"},
            ],
            "plan two turns ago": [
                *hermes_history("thanks")[:2],
                {"role": "user", "content": "thanks"},
                {"role": "assistant", "content": "Anytime."},
                {"role": "user", "content": "구현하기"},
            ],
            "other skill loaded": [
                {"role": "user", "content": "review the diff"},
                {"role": "assistant", "content": "", "tool_calls": unrelated_skill},
                {"role": "user", "content": "구현하기"},
            ],
            "plan named by the user only": [
                {"role": "user", "content": "is .hermes/plans/ ignored by git?"},
                {"role": "assistant", "content": "Yes."},
                {"role": "user", "content": "구현하기"},
            ],
        }
        for label, history in histories.items():
            with self.subTest(history=label):
                self.assertFalse(plan_just_made(history))


class FollowOnLineTests(unittest.TestCase):
    def test_plan_turn_line_only_on_the_plan_frame(self) -> None:
        self.assertEqual(plan_turn_line(PLAN_TURN), PLAN_TURN_LINE)
        for message in ("/plan add CSV export", "plan the CSV export", "[/loop wakeup #3, every 5m]\nRecurring task: x", None):
            with self.subTest(message=message):
                self.assertEqual(plan_turn_line(message), "")

    def test_acceptance_after_a_hermes_plan(self) -> None:
        for message in ACCEPTANCES:
            with self.subTest(message=message):
                self.assertEqual(acceptance_line(message, hermes_history(message), None), ACCEPTANCE_LINE)

    def test_acceptance_while_a_planning_workflow_is_active(self) -> None:
        for workflow in plan_follow_on.PLANNING_WORKFLOWS:
            for message in ACCEPTANCES:
                with self.subTest(workflow=workflow, message=message):
                    active = {"state": "active", "workflow": workflow}
                    self.assertEqual(acceptance_line(message, [{"role": "user", "content": message}], active), ACCEPTANCE_LINE)

    def test_no_line_without_a_fresh_plan(self) -> None:
        other_active = ({"state": "active", "workflow": "ultrawork"}, {"state": "recovery_required"}, None)
        for message in ACCEPTANCES + ("구현해줘 로그인 페이지", "implement the export button", "carry it out"):
            for active in other_active:
                with self.subTest(message=message, active=active):
                    self.assertEqual(acceptance_line(message, [{"role": "user", "content": message}], active), "")

    def test_no_line_on_a_plan_turn_that_is_not_acceptance(self) -> None:
        for message in NOT_ACCEPTANCES:
            with self.subTest(message=message):
                self.assertEqual(acceptance_line(message, hermes_history(message), None), "")

    def test_planning_workflows_are_the_states_dag_ulw_follows(self) -> None:
        self.assertEqual(
            plan_follow_on.PLANNING_WORKFLOWS,
            frozenset(source for source, targets in ALLOWED_TRANSITIONS.items() if "dag-ulw" in targets),
        )

    def test_planning_skill_names_are_the_catalog_names_and_labels(self) -> None:
        from omh.skills.skill_record import skill_record

        workflows = plan_follow_on.PLANNING_WORKFLOWS
        self.assertEqual(
            plan_follow_on.PLANNING_SKILL_NAMES,
            workflows | {skill_record(name).display_name for name in workflows},
        )


class PreLlmCallTests(unittest.TestCase):
    session = "plan-follow-on-session"

    @cached_property
    def home(self) -> Path:
        home = Path(self.enterContext(TemporaryDirectory())) / "omh"
        home.mkdir()
        return home

    def hook(self, message: str, history: list[dict[str, object]] | None = None, **kwargs) -> str:
        payload = llm_hooks.pre_llm_call(
            omh_home=str(self.home), hermes_home=str(self.home.parent / "hermes"), session_id=self.session,
            user_message=message, is_first_turn=False, platform="cli",
            conversation_history=history if history is not None else [{"role": "user", "content": message}],
            **kwargs,
        ) or {}
        return str(payload.get("context", ""))

    def test_plan_turn_carries_the_offer(self) -> None:
        self.assertIn(PLAN_TURN_LINE, self.hook(PLAN_TURN, [{"role": "user", "content": PLAN_TURN}]))

    def test_acceptance_turn_carries_the_offer_on_both_paths(self) -> None:
        for message in ACCEPTANCES:
            with self.subTest(path="hermes /plan", message=message):
                self.assertIn(ACCEPTANCE_LINE, self.hook(message, hermes_history(message)))
        status, _, stderr = run_cli(["--omh-home", str(self.home), "state", "start", "--workflow", "plan",
                                     "--session-ref", self.session])
        self.assertEqual((status, stderr), (0, ""))
        for message in ACCEPTANCES:
            with self.subTest(path="omh plan state", message=message):
                context = self.hook(message)
                self.assertIn("[OMH Active Workflow] workflow=plan", context)
                self.assertIn(ACCEPTANCE_LINE, context)

    def test_a_delegated_child_and_a_home_without_dag_ulw_get_nothing(self) -> None:
        message = ACCEPTANCES[0]
        with mock.patch.object(llm_hooks, "session_is_delegated", return_value=True):
            self.assertNotIn("[OMH Plan Follow-on]", self.hook(message, hermes_history(message)))
        with mock.patch.object(llm_hooks, "hermes_loadable_skill_names", return_value=frozenset({"plan"})):
            self.assertNotIn("[OMH Plan Follow-on]", self.hook(message, hermes_history(message)))
            self.assertNotIn("[OMH Plan Follow-on]", self.hook(PLAN_TURN, [{"role": "user", "content": PLAN_TURN}]))

    def test_turns_without_a_fresh_plan_are_byte_identical(self) -> None:
        # The whole context with the reader switched off is the context before it existed.
        cases = [
            ("구현해줘 로그인 페이지", None),
            ("looks good, implement the plan", None),
            ("implement the export button", None),
            ("carry it out", [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "hello"},
                              {"role": "user", "content": "carry it out"}]),
        ] + [(message, hermes_history(message)) for message in NOT_ACCEPTANCES if message]
        def fresh(message: str, history: list[dict[str, object]] | None) -> str:
            # A fresh home and fresh in-process claims, so neither run spends the other's route hint.
            llm_hooks._reset_awareness_section_state()
            reset_candidate_line_state()
            with TemporaryDirectory() as tmp:
                payload = llm_hooks.pre_llm_call(
                    omh_home=tmp, hermes_home=tmp, session_id=self.session, user_message=message,
                    is_first_turn=False, platform="cli",
                    conversation_history=history or [{"role": "user", "content": message}],
                ) or {}
            return str(payload.get("context", ""))

        for message, history in cases:
            with self.subTest(message=message):
                with_reader = fresh(message, history)
                with mock.patch.object(llm_hooks, "acceptance_line", lambda *args: ""), \
                        mock.patch.object(llm_hooks, "plan_turn_line", lambda *args: ""):
                    without_reader = fresh(message, history)
                self.assertEqual(with_reader, without_reader)


if __name__ == "__main__":
    unittest.main()
