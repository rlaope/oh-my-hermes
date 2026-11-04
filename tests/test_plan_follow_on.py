"""`dag-ulw` is offered on `/plan`'s turn and, conditionally, once on the turn right after a plan was made.

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
    reset_plan_follow_on_state,
)

PLAN_TURN = (
    "[/plan — plan mode]\n\nFor this turn, you are in PLAN MODE — planning only.\n\n"
    "- Do not implement code.\n\nTask to plan:\nadd CSV export to the reports page\n"
)
PLAN_PATH = ".hermes/plans/2026-11-04_101500-export.md"
PLAN_REPLY = f"Saved the plan to {PLAN_PATH} (T1-T5). Want me to carry it out?"
# The six acceptance messages the owner's path produced.
ACCEPTANCES = (
    "좋아 이 플랜대로 구현해줘",
    "구현하기",
    "accepted, carry it out",
    "looks good, implement the plan",
    f"Yes, execute the plan in {PLAN_PATH}",
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
    "go",
    "그렇게 해",
    "let's do this",
)
# Read right after a plan, none of these passes the pre-filter, by category.
NOT_ACCEPTANCES = {
    "change": ("T3을 Redis로 바꿔줘", "no, rewrite the plan around the queue", "Before you start, add a lint step",
               "좋아 근데 T2는 빼고"),
    "question": ("what does T4 test?", "구현은 T1부터 시작하는 거지?", "왜 T5가 마지막이야", "go ahead?", "start now?"),
    "no go word": ("the plan", "이 플랜", "please"),
    "hold or decline": ("hold on, I need to check with the team", "구현은 나중에 하자", "아직 진행 말고 기다려",
                        "실행하지 말아줘", "개발 안 할 거야", "진행 보류", "시작하지 마", "not yet, go later"),
    "closing": ("ok got it", "응 알았어", "좋아 고마워요", "thanks, looks good", "네 확인했어요"),
    "partial or edited": ("T2만 구현해", "4번 빼고 진행", "go ahead but without the cache", "proceed except T5",
                          "테스트 먼저 진행해"),
    "named path": ("run it with dag-ulw", "ultrawork로 진행해", "직접 구현해", "implement it with subagents",
                   "opencode로 실행해", "gemini한테 시켜", "run it in parallel", "순서대로 차례차례 진행",
                   "you implement it alone"),
    "topic change": ("빌드 시작해줘", "run the linter", "start a new branch", "회의록 작성 시작해"),
    "long": ("ok I will read the whole plan tonight with my coworkers and we can talk about it tomorrow morning",),
    "empty": ("",),
}


def hermes_history(message: str) -> list[dict[str, object]]:
    return [
        {"role": "user", "content": PLAN_TURN},
        {"role": "assistant", "content": PLAN_REPLY},
        {"role": "user", "content": message},
    ]


def call(name: str, arguments: object) -> dict[str, object]:
    return {"id": "c1", "type": "function", "function": {"name": name, "arguments": arguments}}


def turn_with(rows: list[dict[str, object]], message: str = "구현하기") -> list[dict[str, object]]:
    return [{"role": "user", "content": "keep going"}, *rows, {"role": "user", "content": message}]


class AcceptsPlanTests(unittest.TestCase):
    def test_acceptances_pass(self) -> None:
        for message in ACCEPTANCES + MORE_ACCEPTANCES:
            with self.subTest(message=message):
                self.assertTrue(accepts_plan(message))

    def test_other_messages_do_not(self) -> None:
        for category, messages in NOT_ACCEPTANCES.items():
            for message in messages:
                with self.subTest(category=category, message=message):
                    self.assertFalse(accepts_plan(message))

    def test_a_path_is_skipped_not_read(self) -> None:
        self.assertTrue(accepts_plan(f"execute {PLAN_PATH}"))
        self.assertFalse(accepts_plan("execute src/loop/x.py later"))


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

    def test_plan_file_written(self) -> None:
        writes = {
            "write_file, JSON string": call("write_file", json.dumps({"path": PLAN_PATH, "content": "# Plan"})),
            "write_file, dict": call("write_file", {"path": PLAN_PATH, "content": "# Plan"}),
            "patch": call("patch", json.dumps({"path": ".omh/plans/export.md", "old_string": "a", "new_string": "b"})),
            "patch, V4A": call("patch", {"mode": "patch", "patch": f"*** Begin Patch\n*** Update File: {PLAN_PATH}\n@@\n-a\n+b"}),
        }
        for label, write in writes.items():
            with self.subTest(write=label):
                self.assertTrue(plan_just_made(turn_with([{"role": "assistant", "content": "", "tool_calls": [write]}])))

    def test_planning_skill_loaded_the_turn_before(self) -> None:
        for name in ("omh-plan", "ulw-plan", "planning/omh-refactor-plan"):
            with self.subTest(name=name):
                load = call("skill_view", json.dumps({"name": name}))
                self.assertTrue(plan_just_made(turn_with([{"role": "assistant", "content": "", "tool_calls": [load]}])))

    def test_planning_skill_invoked_by_slash(self) -> None:
        frame = (
            '[IMPORTANT: The user has invoked the "omh-plan" skill, indicating they want you to follow its '
            "instructions. The full skill content is loaded below.]\n\n# Plan\n\n"
            "The user has provided the following instruction alongside the skill invocation: plan CSV export"
        )
        history = [{"role": "user", "content": frame}, {"role": "assistant", "content": "T1..T4"},
                   {"role": "user", "content": "ok go ahead"}]
        self.assertTrue(plan_just_made(history))

    def test_reads_mentions_and_other_writes_do_not_count(self) -> None:
        cases = {
            "plan file read": [{"role": "assistant", "content": "", "tool_calls": [
                call("read_file", json.dumps({"path": PLAN_PATH}))]}],
            "plan file searched": [{"role": "assistant", "content": "", "tool_calls": [
                call("search_files", {"pattern": "T2", "path": ".hermes/plans/"})]}],
            "plan dir in a shell command": [{"role": "assistant", "content": "", "tool_calls": [
                call("terminal", json.dumps({"command": f"cat {PLAN_PATH}"}))]}],
            "prose naming the plan file": [{"role": "assistant", "content": f"Hermes keeps plans in {PLAN_PATH}."}],
            "a tool result naming it": [{"role": "tool", "tool_call_id": "c1", "content": f"wrote {PLAN_PATH}"}],
            "code written elsewhere": [{"role": "assistant", "content": "", "tool_calls": [
                call("write_file", json.dumps({"path": "src/export.py", "content": "# see .hermes/plans/x.md"}))]}],
            "another skill loaded": [{"role": "assistant", "content": "", "tool_calls": [
                call("skill_view", json.dumps({"name": "code-review"}))]}],
        }
        for label, rows in cases.items():
            with self.subTest(case=label):
                self.assertFalse(plan_just_made(turn_with(rows)))

    def test_no_plan_before_this_turn(self) -> None:
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
        }
        for label, history in histories.items():
            with self.subTest(history=label):
                self.assertFalse(plan_just_made(history))

    def test_carrying_the_plan_out_does_not_reopen_it(self) -> None:
        # The person chose to carry it out directly; the next turn reads the plan and asks to go on.
        history = [
            *hermes_history("직접 구현해"),
            {"role": "assistant", "content": "", "tool_calls": [call("read_file", json.dumps({"path": PLAN_PATH}))]},
            {"role": "assistant", "content": f"T1 done per {PLAN_PATH}. 다음 T2 진행할까요?"},
            {"role": "user", "content": "네"},
        ]
        self.assertEqual(acceptance_line("네", history, None, "s"), "")


class FollowOnLineTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_plan_follow_on_state()
        self.addCleanup(reset_plan_follow_on_state)

    def test_lines_only_offer_and_defer_to_the_message(self) -> None:
        for line in (PLAN_TURN_LINE, ACCEPTANCE_LINE):
            with self.subTest(line=line[:40]):
                self.assertIn("one option beside carrying it out directly", line)
                self.assertIn("disjoint write scopes) ending in a verification task", line)
                self.assertIn("with the fit reason in one line", line)
        self.assertIn("Start nothing they did not pick.", ACCEPTANCE_LINE)
        self.assertIn("If they declined, held, edited, asked something or changed topic, ignore this note.", ACCEPTANCE_LINE)
        self.assertNotIn("Otherwise", ACCEPTANCE_LINE)

    def test_plan_turn_line_only_on_the_plan_frame(self) -> None:
        self.assertEqual(plan_turn_line(PLAN_TURN), PLAN_TURN_LINE)
        for message in ("/plan add CSV export", "plan the CSV export", "[/loop wakeup #3, every 5m]\nRecurring task: x", None):
            with self.subTest(message=message):
                self.assertEqual(plan_turn_line(message), "")

    def test_acceptance_after_a_hermes_plan(self) -> None:
        for message in ACCEPTANCES:
            with self.subTest(message=message):
                self.assertEqual(acceptance_line(message, hermes_history(message), None, "s"), ACCEPTANCE_LINE)

    def test_planning_state_counts_once_per_activation(self) -> None:
        for workflow in plan_follow_on.PLANNING_WORKFLOWS:
            active = {"state": "active", "workflow": workflow}
            for message in ACCEPTANCES:
                with self.subTest(workflow=workflow, message=message):
                    reset_plan_follow_on_state()
                    only = [{"role": "user", "content": message}]
                    self.assertEqual(acceptance_line(message, only, active, "s"), ACCEPTANCE_LINE)
                    # The same state on a later turn is not a fresh plan.
                    self.assertEqual(acceptance_line(message, only, active, "s"), "")
        only = [{"role": "user", "content": "구현하기"}]
        active = {"state": "active", "workflow": "plan"}
        # The first sight is spent on the turn right after activation, whatever it says.
        reset_plan_follow_on_state()
        self.assertEqual(acceptance_line("T3을 바꿔줘", only, active, "s"), "")
        self.assertEqual(acceptance_line("구현하기", only, active, "s"), "")
        # A turn without the state re-arms it; a new activation counts again, per session.
        self.assertEqual(acceptance_line("구현하기", only, None, "s"), "")
        self.assertEqual(acceptance_line("구현하기", only, active, "s"), ACCEPTANCE_LINE)
        self.assertEqual(acceptance_line("구현하기", only, active, "other"), ACCEPTANCE_LINE)

    def test_no_line_without_a_fresh_plan(self) -> None:
        other_active = ({"state": "active", "workflow": "ultrawork"}, {"state": "recovery_required"}, None)
        for message in ACCEPTANCES + ("구현해줘 로그인 페이지", "implement the export button", "carry it out"):
            for active in other_active:
                with self.subTest(message=message, active=active):
                    self.assertEqual(acceptance_line(message, [{"role": "user", "content": message}], active, "s"), "")

    def test_no_line_after_a_plan_on_other_messages(self) -> None:
        for category, messages in NOT_ACCEPTANCES.items():
            for message in messages:
                with self.subTest(category=category, message=message):
                    self.assertEqual(acceptance_line(message, hermes_history(message), None, "s"), "")

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

    def setUp(self) -> None:
        reset_plan_follow_on_state()
        self.addCleanup(reset_plan_follow_on_state)

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
                reset_plan_follow_on_state()
                context = self.hook(message)
                self.assertIn("[OMH Active Workflow] workflow=plan", context)
                self.assertIn(ACCEPTANCE_LINE, context)
                self.assertNotIn("[OMH Plan Follow-on]", self.hook(message))

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
        ] + [(message, hermes_history(message)) for messages in NOT_ACCEPTANCES.values() for message in messages if message]

        def fresh(message: str, history: list[dict[str, object]] | None) -> str:
            # A fresh home and fresh in-process claims, so neither run spends the other's route hint.
            llm_hooks._reset_awareness_section_state()
            reset_candidate_line_state()
            reset_plan_follow_on_state()
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
