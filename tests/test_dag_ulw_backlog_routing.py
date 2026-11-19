"""A backlog of separate code changes, handed over as a list, is made in the current session, not split.

`dag_ulw_cues.lists_several_code_changes` reads the shape: four or more list items that each say a change, in a request
whose own words ask for all of them and name code. The router answers it in the session (`code_backlog`) before any
lane's word in one item can claim the list, and Hermes' per-turn route hint offers nothing, so no dag-ulw graph and no
child agents start: paired runs measured a graph slower than Hermes alone on such a backlog at equal quality. The
routed outcomes are pinned in the corpus (`quality/routing_precision.py`); these pin the reading itself, the injected
text, the agreement of router and hint, the standalone bundle, and the live-information guard that took the paired-run
job before.
"""

from __future__ import annotations

import unittest
from tempfile import TemporaryDirectory

from _local_package import load_local_package
from _standalone_bundle import _load_standalone_bundle_awareness

load_local_package()

from omh.plugin_bundle.omh.awareness import awareness_route_hint  # noqa: E402
from omh.plugin_bundle.omh.dag_ulw_cues import BACKLOG_MIN_ITEMS, lists_several_code_changes  # noqa: E402
from omh.plugin_bundle.omh.hooks import llm_hooks  # noqa: E402
from omh.plugin_bundle.omh.plan_follow_on import reset_plan_follow_on_state  # noqa: E402
from omh.plugin_bundle.omh.reference_regions import executable_routing_text  # noqa: E402
from omh.plugin_bundle.omh.skill_shortlist import reset_candidate_line_state  # noqa: E402
from omh.routing.chat import recommend_route_summary, route_chat_message  # noqa: E402

_LEDGER_ITEMS = (
    "parse_amount('0.2') gives 2 cents instead of 20",
    "export_csv breaks on names with commas",
    "oldest_lot_age crashes after load_lots",
    "the aging report counts invoices twice",
    "the cli prints a traceback on an empty file",
)


def _listed(head: str, count: int, *, marker: str = "{n}.") -> str:
    lines = [f"{marker.format(n=index + 1)} {item}" for index, item in enumerate(_LEDGER_ITEMS[:count])]
    return head + "\n" + "\n".join(lines)


BACKLOGS = (
    _listed("These issues are open against ledgerkit. Fix all of them and keep the tests passing.", 4),
    _listed("Fix these bugs in the repo:", 5, marker="-"),
    _listed("Please resolve each of these in the codebase:", 4, marker="*"),
    _listed("Work through this backlog in the package:", 4, marker="{n})"),
    "Please implement the following in our API, each is its own change:\n- add pagination to the /users endpoint\n"
    "- add a created_at filter to the orders list\n- return 404 instead of 500 for unknown product ids\n"
    "- add a health check endpoint that pings the database",
    "아래 버그들 전부 고쳐줘\n1. 로그인 후 세션이 만료되지 않음\n2. 결제 모듈에서 환불 금액이 음수로 저장됨\n"
    "3. 알림 API가 중복으로 발송됨\n4. 검색 결과 페이지네이션이 마지막 페이지를 건너뜀",
    # A period word naming a thing (the monthly report, a weekly digest) is no schedule.
    _listed("The package's monthly report and weekly digest modules have these bugs. Fix all of them:", 4),
)

NOT_BACKLOGS = (
    # Too small: one change, or a list of two or three.
    "parse_amount('0.2') gives 2 cents instead of 20 cents. Fix it.",
    _listed("Fix these bugs:", 2),
    _listed("Fix these bugs:", 3),
    # The list is looked at, sorted, planned or filed, not changed.
    _listed("Which of these bugs should I fix first?", 4),
    _listed("Can you review these four fixes before I merge them?", 4),
    _listed("Prioritize this backlog for the next sprint:", 4),
    _listed("Explain why each of these bugs happens:", 4),
    _listed("Turn these bug reports into GitHub issues:", 4),
    _listed("Write a plan for fixing these bugs:", 4),
    _listed("Don't fix anything yet, just tell me what is wrong in each:", 4),
    "아래 변경사항 리뷰해줘\n1. 로그인 세션 만료 처리 추가\n2. 환불 금액 검증 로직 수정\n3. 알림 API 중복 발송 방지\n"
    "4. 검색 페이지네이션 버그 수정",
    # Held, put off, or handed to a named coding agent.
    _listed("Fix all of these bugs next week:", 4),
    # A period word said of the work itself is a schedule, so the list stays out of a graph.
    _listed("Fix these bugs in the repo monthly:", 4),
    _listed("Rebase and fix these in the package nightly, then report:", 4),
    _listed("Fix these bugs in the repo weekly and post the result:", 4),
    _listed("Have codex fix all of these bugs:", 4),
    # A quoted or fenced list is not the request's own.
    "Fix all of these:\n```\n" + _listed("", 4).strip() + "\n```",
    # Items that are no change of their own: test files by path.
    "fix these failing tests:\n- tests/test_amounts.py\n- tests/test_lots.py\n- tests/test_export.py\n- tests/test_aging.py",
    # No code: chores, a reading list, a Korean to-do list.
    "Please do all of these today:\n1. buy milk and eggs at the store\n2. call the dentist about Friday\n"
    "3. pick up the dry cleaning downtown\n4. book a table for Saturday dinner",
    "Summarize all of these articles for me:\n1. the history of the Roman empire\n2. a guide to sourdough baking at home\n"
    "3. how tides work on the Atlantic coast\n4. why cats knock things off tables",
    "오늘 할 일 전부 정리해줘\n1. 우유랑 계란 사기\n2. 치과 예약 전화하기\n3. 세탁소 옷 찾기\n4. 토요일 저녁 식당 예약",
)

# The same backlog said in one line: three or more separate code changes joined by commas, "and", 랑, 하고, 이랑 or
# 와·과. Without the reading, each landed on a lane one item's word scored (toolbelt-readiness on "API",
# browser-operator on "login", backend on "백엔드").
INLINE_BACKLOGS = (
    "로그인 API, 설정 화면, 문서 페이지 세 개를 한 번에 고쳐줘",
    "Fix these four bugs: the export crash, the login redirect, the empty chart, and the broken docs link",
    "프론트 버튼 추가랑 백엔드 엔드포인트랑 테스트 다 해줘",
    "migrate the settings store to sqlite, update the three callers, and add tests",
    # A Korean connector right after a Latin word.
    "로그인 API하고 설정 화면하고 문서 페이지 세 개 다 고쳐줘",
    "로그인 API와 설정 화면과 문서 페이지 세 개 다 고쳐줘",
)

# One-line lists that are no backlog keep the route they had: (message, (action, selected skill, reason code)).
INLINE_NOT_BACKLOGS = (
    # One bug, its symptoms listed.
    ("Fix the login bug: it crashes, shows a blank page, and logs a 500 error", ("dispatch", "ultrawork", None)),
    ("explain these three functions: parse_args, load_config, and run_main",
     ("fallback", "oh-my-hermes", "direct_answer")),
    ("buy milk, eggs, bread and coffee", ("fallback", "oh-my-hermes", None)),
    ("review these 3 PRs: #101, #102, and #103", ("clarify", "oh-my-hermes", None)),
    ("fix the typo in README line 3", ("fallback", "oh-my-hermes", "direct_answer")),
    # One feature that names its parts.
    ("add a login page with email, password and a remember-me box", ("dispatch", "browser-operator", None)),
    # A list of questions, and a list of files to read.
    ("what does parse_args return, why does load_config fail on an empty file, and how do I run the tests?",
     ("clarify", "oh-my-hermes", None)),
    ("read src/cli.py, src/config.py and src/runner.py and tell me how they fit together",
     ("fallback", "oh-my-hermes", "file_lookup")),
)

_HINT_HEAD = "first_response_shape=Start at once: give each listed change its own build node"
_IN_SESSION = "Make the listed code changes in this session, one after another"


class BacklogReadingTests(unittest.TestCase):
    def test_a_listed_backlog_of_code_changes_is_read_as_one(self) -> None:
        for message in BACKLOGS:
            with self.subTest(message=message[:60]):
                self.assertTrue(lists_several_code_changes(executable_routing_text(message)))

    def test_small_looked_at_held_quoted_and_non_code_lists_are_not(self) -> None:
        for message in NOT_BACKLOGS:
            with self.subTest(message=message[:60]):
                self.assertFalse(lists_several_code_changes(executable_routing_text(message)))

    def test_the_item_count_floor_is_four(self) -> None:
        # Pinned as a literal: three listed changes stay one agent's work, four run as a graph.
        self.assertEqual(BACKLOG_MIN_ITEMS, 4)
        head = "These issues are open against ledgerkit. Fix all of them."
        self.assertFalse(lists_several_code_changes(_listed(head, 3)))
        self.assertTrue(lists_several_code_changes(_listed(head, 4)))

    def test_a_list_with_no_code_named_is_not_a_backlog(self) -> None:
        # A change verb over four items, none of them code, and no code in the request's own words.
        self.assertFalse(lists_several_code_changes(
            "Fix all of these around the house:\n1. the leaky faucet in the kitchen\n2. the squeaky hinge on the back "
            "door\n3. the broken lamp in the hallway\n4. the loose tile in the bathroom"
        ))

    def test_a_list_with_no_change_asked_is_not_a_backlog(self) -> None:
        # Four code items handed over, but the request's own words ask for nothing to be changed.
        self.assertFalse(lists_several_code_changes(
            _listed("Here are all the crashes users reported in the cli this week:", 4)
        ))

    def test_a_pull_request_link_is_one_scope(self) -> None:
        message = _listed("Fix all of these review comments in the code:", 4)
        self.assertTrue(lists_several_code_changes(message))
        self.assertFalse(lists_several_code_changes(message, ("https://github.com/o/r/pull/12",)))

    def test_a_one_line_list_of_three_code_changes_is_read_as_one(self) -> None:
        for message in INLINE_BACKLOGS:
            with self.subTest(message=message):
                self.assertTrue(lists_several_code_changes(executable_routing_text(message)))

    def test_one_line_symptoms_parts_questions_and_reading_lists_are_not(self) -> None:
        for message, _route in INLINE_NOT_BACKLOGS:
            with self.subTest(message=message):
                self.assertFalse(lists_several_code_changes(executable_routing_text(message)))

    def test_verb_led_errands_with_one_code_word_and_foreign_letters_are_not(self) -> None:
        for message in (
            "Fix the venue name, update the dates, and add the dress code to the invitation",
            "Fix the typo, update the date, and add tests to the printed lab syllabus",
            "Fix the foyer sign, update the opening hours, and add the library address",
            "Fix the author name, update the cover date, and add a migration photo to the brochure",
            "Fix the apiño spelling, update the cover date, and add page numbers",
            "Fix the dress code, update the library hours, and add a reception sign",
            # "and" joining two verbs of one change is no list separator.
            "Run a loop to find and fix OMH router context-loss and coding handoff bugs with progress evidence.",
        ):
            with self.subTest(message=message):
                self.assertFalse(lists_several_code_changes(executable_routing_text(message)))

    def test_a_one_line_list_of_two_changes_is_too_small(self) -> None:
        self.assertFalse(lists_several_code_changes("migrate the settings store to sqlite and add tests"))
        self.assertFalse(lists_several_code_changes("로그인 API랑 설정 화면 둘 다 고쳐줘"))

    def test_a_non_string_or_an_oversized_message_is_not_read(self) -> None:
        self.assertFalse(lists_several_code_changes(None))  # type: ignore[arg-type]
        self.assertFalse(lists_several_code_changes(_listed("Fix all of these bugs:", 4) + "\n" + "x " * 7000))


class BacklogRoutingTests(unittest.TestCase):
    def test_the_router_answers_in_the_session_and_the_hint_offers_nothing(self) -> None:
        for message in BACKLOGS:
            with self.subTest(message=message[:60]):
                route = route_chat_message(message, source="discord")
                self.assertEqual(
                    (route["action"], route["selected_skill"], route.get("reason_code")),
                    ("fallback", "oh-my-hermes", "code_backlog"),
                )
                self.assertTrue(route["routing_prompt"].startswith(_IN_SESSION))
                self.assertEqual(awareness_route_hint(message)["hints"], [])

    def test_a_one_line_backlog_is_answered_in_the_session_too(self) -> None:
        for message in INLINE_BACKLOGS:
            with self.subTest(message=message):
                route = route_chat_message(message, source="discord")
                self.assertEqual(
                    (route["action"], route["selected_skill"], route.get("reason_code")),
                    ("fallback", "oh-my-hermes", "code_backlog"),
                )
                self.assertTrue(route["routing_prompt"].startswith(_IN_SESSION))
                self.assertEqual(awareness_route_hint(message)["hints"], [])
                self.assertEqual(recommend_route_summary(message)["action"], "fallback")

    def test_one_line_look_alikes_keep_their_route(self) -> None:
        for message, expected in INLINE_NOT_BACKLOGS:
            with self.subTest(message=message):
                route = route_chat_message(message, source="discord")
                self.assertEqual((route["action"], route["selected_skill"], route.get("reason_code")), expected)
                self.assertNotIn("dag-ulw", [hint.get("workflow") for hint in awareness_route_hint(message)["hints"]])

    def test_no_negative_is_started_or_offered_a_graph(self) -> None:
        for message in NOT_BACKLOGS:
            with self.subTest(message=message[:60]):
                route = route_chat_message(message, source="discord")
                self.assertNotEqual(route["selected_skill"], "dag-ulw")
                self.assertNotEqual(route.get("reason_code"), "code_backlog")

    def test_a_skill_invoked_by_name_keeps_the_backlog(self) -> None:
        message = _listed("ulw-plan: fix all of these bugs in the repo", 4)
        route = route_chat_message(message, source="discord")
        self.assertNotEqual(route["selected_skill"], "dag-ulw")
        self.assertNotEqual(route.get("reason_code"), "code_backlog")
        # dag-ulw by name still runs the list as a graph: the person asked for it.
        named = route_chat_message(_listed("dag-ulw: fix all of these bugs in the repo", 4), source="discord")
        self.assertEqual((named["action"], named["selected_skill"]), ("dispatch", "dag-ulw"))

    def test_work_over_many_targets_still_runs_as_a_graph(self) -> None:
        # Not a listed backlog: the breadth dispatch the backlog rule sat beside is unchanged.
        route = route_chat_message("열린 PR들 전부 리베이스해줘", source="discord")
        self.assertEqual((route["action"], route["selected_skill"]), ("dispatch", "dag-ulw"))

    def test_the_hint_is_the_same_on_a_host_without_the_package(self) -> None:
        standalone = _load_standalone_bundle_awareness()
        for message in (*BACKLOGS[:3], *NOT_BACKLOGS[:4]):
            with self.subTest(message=message[:60]):
                self.assertEqual(
                    [(hint.get("workflow"), hint.get("id")) for hint in standalone.awareness_route_hint(message)["hints"]],
                    [(hint.get("workflow"), hint.get("id")) for hint in awareness_route_hint(message)["hints"]],
                )


class BacklogInjectionTests(unittest.TestCase):
    session = "dag-ulw-backlog-session"

    def setUp(self) -> None:
        for reset in (llm_hooks._reset_awareness_section_state, reset_candidate_line_state, reset_plan_follow_on_state):
            reset()
            self.addCleanup(reset)

    def context(self, message: str) -> str:
        with TemporaryDirectory() as tmp:
            payload = llm_hooks.pre_llm_call(
                omh_home=tmp, hermes_home=tmp, session_id=self.session, user_message=message, is_first_turn=True,
                platform="cli", conversation_history=[{"role": "user", "content": message}],
            ) or {}
        return str(payload.get("context", ""))

    def test_a_backlog_turn_starts_no_graph_and_no_lane(self) -> None:
        for message in BACKLOGS:
            with self.subTest(message=message[:60]):
                for reset in (llm_hooks._reset_awareness_section_state, reset_candidate_line_state,
                              reset_plan_follow_on_state):
                    reset()
                context = self.context(message)
                self.assertNotIn("selected=dag-ulw", context)
                self.assertNotIn("next_action=start_dag_run", context)
                self.assertNotIn(_HINT_HEAD, context)
                # The pilot's misdirection stays gone: no lane one item's word scored is offered either.
                self.assertNotIn("selected=live-info-operator", context)

    def test_a_small_or_other_list_turn_carries_no_backlog_instruction(self) -> None:
        for message in NOT_BACKLOGS:
            with self.subTest(message=message[:60]):
                for reset in (llm_hooks._reset_awareness_section_state, reset_candidate_line_state,
                              reset_plan_follow_on_state):
                    reset()
                context = self.context(message)
                self.assertNotIn(_HINT_HEAD, context)
                self.assertNotIn("next_action=start_dag_run", context)


class CurrentWorkspaceIsNoLiveLookupTests(unittest.TestCase):
    def test_current_said_of_the_workspace_reaches_no_live_information(self) -> None:
        for message in (
            "In the current directory, the invoice total in invoice.py rounds half cents down; fix it to round half up.",
            "Check the current branch and the time it was created",
            "You are working in the current directory, a package with stock lots. What does get_lot return?",
        ):
            with self.subTest(message=message):
                self.assertNotEqual(route_chat_message(message, source="discord")["selected_skill"], "live-info-operator")

    def test_a_live_lookup_said_with_current_still_reaches_it(self) -> None:
        # "current price of the stock" has no live cue but "current": it must stay a live lookup.
        for message in ("what's the current stock price of AAPL", "check the current time in Tokyo",
                        "current weather in Seoul", "current price of the stock"):
            with self.subTest(message=message):
                self.assertEqual(route_chat_message(message, source="discord")["selected_skill"], "live-info-operator")


if __name__ == "__main__":
    unittest.main()
