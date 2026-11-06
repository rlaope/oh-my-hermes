"""Reaching `dag-ulw`: by its two-word name the way people type it, and by intent for big parallel work.

The corpus cases in `quality/routing_precision.py` hold the routed outcome;
these pin the readings it rests on (`dag_ulw_cues`: the name, a question
about it, and big work by size), that the router and Hermes' own route hint
read them alike, and that the bare words stay where they were: `dag` with
data pipelines, `ulw` / `ultrawork` with `ultrawork`.
"""

from __future__ import annotations

import unittest
from unittest import mock

from _local_package import load_local_package
from _standalone_bundle import _load_standalone_bundle_awareness

load_local_package()

from omh.plugin_bundle.omh.awareness import awareness_route_hint, awareness_route_hint_context_from_payload  # noqa: E402
from omh.plugin_bundle.omh.reference_regions import reference_regions  # noqa: E402
from omh.plugin_bundle.omh.dag_ulw_cues import (  # noqa: E402
    asks_about_dag_ulw,
    big_work_for_dag_ulw,
    dag_ulw_control,
    declines_dag_ulw,
    dispatches_dag_ulw,
    refuses_dag_ulw,
    invokes_dag_ulw,
    names_several_features,
    work_over_many_targets,
)
from omh.routing.chat import route_chat_message  # noqa: E402
from omh.routing.policy import skill_is_negated  # noqa: E402

INVOKES = (
    "dag ulw add the export API and its docs",
    "dag ulw해줘 결제 모듈이랑 알림 모듈",
    "dag ulw로 해줘",
    "dag ulw 해주세요",
    "결제 모듈 dag ulw로 고쳐줘",
    "ulw dag split the auth refactor",
    "/dag-ulw build the search feature",
    "$dag-ulw refactor the parser",
    "./dag-ulw 해줘",
    "use dag ulw for the release checklist",
    "please dag ulw the migration",
    "refactor the billing modules with dag ulw",
    "Dag-ULW 해주세요",
    "dag ultrawork the onboarding flow",
    # A request put politely as a question.
    "can you dag ulw the migration?",
    "could you please dag ulw the billing refactor",
    "could you run dag ulw on the billing refactor?",
    # An `or` between two targets weighs nothing.
    "can you dag ulw the auth or billing refactor?",
)
DOES_NOT_INVOKE = (
    "don't use dag ulw for this, just fix the typo",
    "dag ulw 말고 그냥 고쳐줘",
    "dag ulw는 쓰지 마",
    "not dag ulw, just answer",
    "the airflow dag failed last night",
    "open the dag file",
    "is dag ulw any good?",
    "어제 돌린 dag ulw 결과가 어떻게 됐어?",
    # Questions about the skill, answered as a question about any other skill is.
    "dag ulw는 뭐야?",
    "dag ulw 설명해줘",
    "dag ulw 결과 알려줘",
    "dag ulw 문서 보여줘",
    "dag ulw 어떻게 써?",
    "dag ulw 쓰면 비용이 얼마나 나와?",
    "dag ulw is broken, it never settles the verify node",
    "how does dag-ulw handle repairs?",
    "tell me about dag-ulw",
    "can you explain dag ulw?",
    "could you describe dag ulw",
    "can you not dag ulw this?",
    # A polite question that weighs the run against another way, or asks what you would do.
    "can you dag ulw this or should I just fix it myself?",
    "would you dag ulw, or just ultrawork, the auth refactor?",
    "could you dag ulw this, or is that overkill?",
    "would you dag ulw this or not?",
    "can you dag ulw the migration? or is that overkill",
    "would you dag ulw it, if you were me?",
    "can you dag ulw the migration 아니면 그냥 ultrawork로 할까?",
    # Asking to stop using it declines it.
    "can you stop using dag ulw for small fixes?",
    "ulw dagger",
    "ulw로 다 고쳐줘",
    "ultrawork the auth refactor",
)


class InvocationTests(unittest.TestCase):
    def test_the_name_in_the_shapes_people_type_invokes_it(self) -> None:
        for message in INVOKES:
            with self.subTest(message=message):
                self.assertTrue(invokes_dag_ulw(message))

    def test_a_declined_bare_or_merely_mentioned_name_does_not(self) -> None:
        for message in DOES_NOT_INVOKE:
            with self.subTest(message=message):
                self.assertFalse(invokes_dag_ulw(message))

    def test_a_declined_name_leaves_the_candidate_list(self) -> None:
        self.assertTrue(declines_dag_ulw("don't use dag ulw for this"))
        self.assertTrue(skill_is_negated("dag ulw 말고 그냥 고쳐줘", "dag-ulw"))
        self.assertFalse(skill_is_negated("dag ulw add the API", "dag-ulw"))


class RouterTests(unittest.TestCase):
    def test_the_explicit_forms_dispatch_dag_ulw(self) -> None:
        for message in ("dag ulw해줘 결제 모듈이랑 알림 모듈 같이 리팩터링해", "ulw dag split the auth refactor across the service",
                        "refactor the billing and invoicing modules with dag ulw",
                        # A failure that is the work, or a report with a request after it, still runs it.
                        "dag ulw the build that broke", "dag ulw 실패한 테스트 고쳐줘", "dag ulw 또 실패했어, 다시 돌려줘",
                        "/dag-ulw broke the build, fix it", "dag ulw failed again, rerun it", "dag ulw why the build is failing",
                        # Work on a cancel, named as such.
                        "dag ulw 결제 취소 처리 로직 구현해줘", "dag ulw 취소 버튼 만들어줘", "dag ulw cancel order flow",
                        "dag ulw add a cancel button", "dag ulw 취소 버튼 눌러도 안 멈추는 버그 고쳐줘",
                        "dag ulw kill switch for flags",
                        # A request after a use clause, or the name said again as the request.
                        "dag ulw 돌리고 나서 PR 올려", "dag ulw failed, dag ulw it again"):
            with self.subTest(message=message):
                route = route_chat_message(message, source="discord")
                self.assertEqual((route["action"], route["selected_skill"]), ("dispatch", "dag-ulw"))

    def test_bare_words_keep_their_owners(self) -> None:
        self.assertEqual(route_chat_message("ultrawork the auth refactor across the service")["selected_skill"],
                         "ultrawork")
        self.assertEqual(route_chat_message("$ulw-work fix the build")["selected_skill"], "ultrawork")
        for message in ("the airflow dag failed last night, check the scheduler logs", "open the dag file"):
            with self.subTest(message=message):
                route = route_chat_message(message)
                self.assertNotEqual(route["candidate_skill"], "dag-ulw")

    def test_size_evidence_reads_how_the_work_splits_or_how_wide_it_reaches(self) -> None:
        for message in ("implement the export feature in parallel across the api and ui modules",
                        "api, ui, docs 작업을 병렬로 나눠서 만들어줘", "migrate every module from requests to httpx",
                        "fan out across the services, then integrate"):
            with self.subTest(message=message):
                self.assertTrue(big_work_for_dag_ulw(message))
        for message in ("fix the flaky checkout test", "README 오타 고쳐줘",
                        # A concurrency word or a second step that names the subject, not the work's shape.
                        "fix the bug where uploads run in parallel and corrupt the file", "병렬 처리 버그 고쳐줘",
                        "동시에 두 요청이 오면 캐시가 깨지는 버그 고쳐줘", "병렬로 진행되는 작업이 데드락 걸리는 버그 고쳐줘",
                        "the parallel work queue drops jobs, fix it", "the fan out of this function is too high, fix it",
                        "add the field to the form, then integrate it with the api",
                        # A fault two named parts cause at once, with one fix asked for.
                        "api 모듈과 ui 모듈이 동시에 요청하면 캐시가 깨져, 고쳐줘",
                        "the payment and order services crashed when called concurrently, fix it",
                        # A remark on a measure, and a small text task.
                        "the fan out across the services is too high", "our split into parallel lanes was too coarse",
                        "split the paragraph into parallel parts for the translation", "이 문단을 병렬로 나눠서 번역해줘",
                        # A question or an explain request about how work splits.
                        "explain how to split the work into parallel lanes", "how do I split the work into parallel lanes?",
                        "what does it mean to fan out across services", "병렬로 나눠서 하는 방법 설명해줘",
                        "help me understand how to fan out across services",
                        "what we need is an explanation of how to split work into parallel lanes",
                        "병렬로 나눠서 하는 방법 알려줘", "병렬로 나눠서 작업하는 방법이 뭐야",
                        "show me how to split the work into parallel lanes", "is it possible to split the work into parallel lanes",
                        # Only the question mark says it: a question, not a request put as one.
                        "should we split the api, ui and docs work into parallel lanes?",
                        "i'd like to know how to split the work into parallel lanes",
                        "why not just explain how to split the work into parallel lanes",
                        # Talking it over, or a split weighed against another way.
                        "can we talk about how to split the work into parallel lanes?",
                        "could we split the work into parallel lanes, or is it overkill?",
                        # A condition clause, not a request, after the concurrency word.
                        "api 모듈과 ui 모듈이 동시에 처리해서 캐시가 깨져, 고쳐줘",
                        "api 모듈과 ui 모듈이 동시에 진행해서 데드락이 걸려 고쳐줘",
                        # Ultrawork named anywhere stays ultrawork's.
                        "fix the auth and billing modules in parallel with ulw"):
            with self.subTest(message=message):
                self.assertFalse(big_work_for_dag_ulw(message))
        for message in ("api 모듈과 ui 모듈 테스트가 실패하는데 병렬로 고쳐줘", "the migration is big, split it into parallel lanes",
                        "can you split the api, ui and docs work into parallel lanes?",
                        "split the paragraphs of the manual into parallel parts for translation",
                        "api, ui, docs 작업을 병렬로 나눠서 구현하고 변경 내용 설명해줘",
                        # Fixes said to run in parallel a word or two on, or the work said to run at once.
                        "api 모듈과 ui 모듈 테스트가 깨졌어, 병렬로 각각 고쳐줘",
                        "api 모듈과 ui 모듈 작업을 동시에 진행해줘, 실패하는 테스트도 고쳐줘",
                        # Openers that propose the work, requests put as questions, and an explain clause after the work.
                        "how about we split the api, ui and docs work into parallel lanes",
                        "why don't we split the api, ui and docs work into parallel lanes",
                        "what we need is to split the api, ui and docs work into parallel lanes",
                        "tell me when done: split the api, ui and docs work into parallel lanes",
                        "can we split the api, ui and docs work into parallel lanes?",
                        "split the api, ui and docs work into parallel lanes, ok?",
                        "api, ui, docs 작업을 병렬로 나눠서 구현해줄 수 있어?",
                        "api, ui, docs 작업을 병렬로 나눠서 구현하고 나눈 방법 설명해줘",
                        # A paragraph or sentence that is not what the split's object is.
                        "split the api, ui and docs work into parallel lanes and fix the paragraph in the README",
                        "split the paragraph parser and the sentence splitter work into parallel lanes",
                        "api, ui, docs 작업을 병렬로 나눠서 구현하고 README 한 문단 추가해줘",
                        "what i want is to split the api, ui and docs work into parallel lanes",
                        "그냥 병렬로 나눠서 하지 뭐", "api, ui, docs 작업을 병렬로 나눠서 진행해주고 다 됐는지 알려줘",
                        "api, ui, docs 작업을 병렬로 나눠서 구현하면 어때?"):
            with self.subTest(message=message):
                # Fixes said to run in parallel, a split asked for after a remark, a polite request, and many paragraphs.
                self.assertTrue(big_work_for_dag_ulw(message))

    def test_ultrawork_capabilities_answer_before_the_size_reading(self) -> None:
        # The retired-engine alias route answers coordinated workers before scoring, lanes phrase or not.
        route = route_chat_message("run three coordinated workers on one shared task list in parallel lanes")
        self.assertEqual((route["action"], route["selected_skill"]), ("dispatch", "ultrawork"))

    def _dag_ulw_starts(self, message: str) -> tuple[bool, bool, str]:
        """Whether the router dispatches dag-ulw, whether the route hint starts it, and the route's candidate."""
        route = route_chat_message(message, source="discord")
        hints = awareness_route_hint(message)["hints"]
        hint_starts = any(hint.get("workflow") == "dag-ulw" and hint.get("next_action") == "start_dag_run" for hint in hints)
        return route["selected_skill"] == "dag-ulw", hint_starts, str(route.get("candidate_skill") or "")

    def test_work_over_many_targets_runs_as_a_graph(self) -> None:
        # Positive evidence (`dispatches_dag_ulw`): a change verb from the allow list, in request form, on a breadth
        # object. The router dispatches dag-ulw whichever lane scored, and the hint starts it on the same reading.
        for message in ("rlaope로 올린 hermes upstream pr들 전부 확인해서 닫을건 닫고 리뷰반영할건 리뷰반영하고 rebase할건 리베이스하고",
                        "열린 PR들 전부 리베이스해줘", "fix all the failing tests", "update every service to node 22",
                        "implement search and export features in parallel", "모든 패키지 버전 올려줘",
                        "브랜치들 전부 main에 맞춰 리베이스해줘", "billing 말고 모든 서비스 node 22로 올려줘",
                        "update the dependencies in all services", "블로그 pr 전부 머지해줘",
                        # A request ending said as a word of its own, or a 해, 놔 or ㄱ ending (#2232 review).
                        "열린 PR들 전부 리베이스 해줘", "모든 서비스 node 22로 업데이트 해주세요", "PR들 다 리베이스해",
                        "모든 패키지 버전 올려놔", "PR들 전부 리베이스 ㄱ", "모든 서비스 업데이트 좀 해줘",
                        # A past or a completion in a modifier names which units.
                        "내가 올렸던 PR들 전부 리베이스해줘", "어제 실패했던 테스트 전부 고쳐줘",
                        "충돌났던 브랜치들 전부 다시 리베이스해줘", "완료된 이슈들 전부 닫아줘",
                        # The owner's English change verbs inside a Korean request, and a push after a change.
                        "hermes upstream에 낸 PR들 전부 확인해서 리뷰 코멘트 반영하고 rebase까지 ㄱㄱ",
                        "열린 PR들 전부 리뷰 코멘트 반영하고 force push ㄱㄱ", "PR들 전부 rebase 해줘",
                        # A change, then a report on it.
                        "fix all the failing tests and tell me which ones were flaky",
                        "fix all the failing tests and report which ones were flaky",
                        # Many PRs or branches stay many: 들, a breadth word or 모든 on the PR or the branch itself.
                        "열린 PR 전부 리베이스해줘", "main 브랜치에 PR들 전부 머지해줘", "모든 PR 테스트 고쳐줘",
                        # A change aimed so a thing does not happen, or units a fault describes, are no fault.
                        "모든 테스트 통과하도록 고쳐줘", "모든 모듈 print 안 쓰게 고쳐줘", "안 돌아가는 테스트 전부 고쳐줘",
                        "모든 페이지 더블클릭 안 되게 고쳐줘",
                        # More request endings, a modifier past, the owner's words (#2232 review 2).
                        "모든 서비스 업데이트 해주세용", "PR들 전부 리베이스해줘요", "모든 서비스 업데이트 해 놔줘", "모든 모듈에 로깅 넣어 줘",
                        "모든 서비스 업데이트 시켜줘", "모든 패키지 버전 올리자", "PR들 전부 리베이스 고", "PR들 전부 리베이스해주셈",
                        "모든 서비스 업데이트 부탁", "충돌났었던 브랜치들 전부 리베이스해줘", "모든 패키지 upgrade해줘",
                        "PR들 전부 확인해서 close할 건 close하고 리베이스하고", "PR들 몽땅 리베이스해줘", "모든 패키지 최신화해줘",
                        "for each of my PRs: rebase onto main and fix the conflicts", "for every open PR, rebase it onto main",
                        # A count of PRs, repos or branches with a breadth word after it is many of them.
                        "PR 3개 전부 리베이스해줘", "PR 5개 다 머지해줘", "레포 3개 전부 의존성 올려줘", "풀리퀘 3개 전부 리베이스해줘",
                        # More breadth words, casual imperatives and request endings, a change asked in one clause,
                        # and a change aimed so a thing does not happen a few words off (#2232 follow-ups).
                        "PR들 쭉 리베이스해줘", "PR들 하나도 빠짐없이 리베이스해줘", "take the failing tests and fix them all",
                        "PR들 전부 닫아", "모든 테스트 고쳐", "모든 패키지 버전 올려라", "PR들 전부 리베이스해주라", "PR들 전부 리베이스 고고싱",
                        "모든 패키지 업데이트해놔라", "모든 서비스 업데이트해주십쇼", "모든 서비스 업데이트 요망",
                        "모든 서비스 업데이트해 주시면 감사하겠습니다", "모든 패키지 업데이트해줘, 패키지마다 changelog도 써줘",
                        "모든 페이지 더블클릭 안 되게끔 수정해줘", "모든 서비스에서 중복 결제가 안 되게 수정해줘",
                        # The same request now is no schedule.
                        "rebase every open PR now", "지금 바로 열린 PR들 전부 리베이스해줘", "이번에 한 번만 열린 PR들 전부 리베이스해줘",
                        # A change aimed so a thing does not happen, with 수정 as with 고쳐.
                        "모든 페이지 버튼 안 보이게 수정해줘", "모든 페이지 링크 안 열리게 수정해줘", "모든 서비스 로그 안 찍히게 수정해줘",
                        "모든 페이지 더블클릭 안 되게 수정해줘"):
            with self.subTest(message=message):
                self.assertTrue(dispatches_dag_ulw(message))
                self.assertEqual(self._dag_ulw_starts(message)[:2], (True, True))
        # Work over many targets without that evidence is offered, never started (`work_over_many_targets`).
        for message in ("review all open PRs", "check all open pull requests and close the stale ones",
                        "migrate across all modules to the new logger"):
            with self.subTest(message=message):
                self.assertFalse(dispatches_dag_ulw(message))
                self.assertTrue(work_over_many_targets(message))
                self.assertEqual(self._dag_ulw_starts(message)[:2], (False, False))
        # Where no rule names it, the hint offers dag-ulw (ask once), and the router asks about it.
        offer = [hint for hint in awareness_route_hint("migrate across all modules to the new logger")["hints"]
                 if hint.get("workflow") == "dag-ulw"]
        self.assertEqual([hint.get("next_action") for hint in offer], ["ask_one_clarification"])
        self.assertEqual(self._dag_ulw_starts("migrate across all modules to the new logger")[2], "dag-ulw")

    def test_several_features_named_to_build_are_offered(self) -> None:
        # Several features or stages, named or counted, as a build verb's object: the hint offers dag-ulw first (ask
        # once), ahead of a rule one item's word matched ("검색" for web-research), and nothing starts.
        for message in ("메일 가져오기, 파일 업로드, 검색 기능 개발해줘", "검색, 필터, 정렬 기능을 붙여줘",
                        "목록, 상세, 저장 기능 전부만들어", "로그인, 목록, 알림 개발해줘", "댓글, 좋아요, 신고 기능 추가해줘",
                        "장바구니랑 주문이랑 배송조회 기능 구현해", "알림 설정과 이메일 발송과 푸시 기능 만들어",
                        "로그인하고 대시보드하고 리포트 기능까지 개발해", "온보딩, 홈, 마이페이지 화면 다 구현하자",
                        "회원가입 로그인부터 일반채팅, 판단질문, 지식그래프, 온톨로지 과정을 설계에 맞게 개발해줘",
                        "회원가입부터 결제까지 개발해줘", "가입부터 탈퇴까지 전부 개발해",
                        "여러 기능 나눠서 다 해줘", "기능 여러 개 한꺼번에 개발해줘", "3개 기능 구현해줘",
                        "add sign-in, billing and export features", "build the upload, preview and download screens",
                        "build search, filters and sorting", "build login, list and notifications",
                        "implement everything from onboarding to checkout",
                        "implement several features",
                        # The neighbours of an obligation stated and of a range that names no stage, below.
                        "로그인, 회원가입, 검색 기능 만들어줘", "회원가입부터 결제까지 만들어줘", "build it from signup to billing"):
            with self.subTest(message=message):
                self.assertTrue(names_several_features(message))
                self.assertFalse(dispatches_dag_ulw(message))
                hint = awareness_route_hint(message)
                # A coding-delivery hint already reads some of them as ultrawork-shaped work and keeps them.
                self.assertIn(hint["selected_workflow"], ("dag-ulw", "ulw-work"))
                if hint["selected_workflow"] == "dag-ulw":
                    self.assertEqual(hint["hints"][0]["next_action"], "ask_one_clarification")
                self.assertEqual(self._dag_ulw_starts(message)[:2], (False, False))
        # The router asks about dag-ulw where it would ask anyway.
        for message in ("장바구니랑 주문이랑 배송조회 기능 구현해", "여러 기능 나눠서 다 해줘"):
            with self.subTest(message=message):
                self.assertEqual(self._dag_ulw_starts(message), (False, False, "dag-ulw"))

    def test_a_list_or_range_without_a_named_feature_stays_off_the_offer(self) -> None:
        # The reading needs positive evidence; these show none, so they read as they did before it existed.
        for message in (
            # One thing the list fills, or a thing the list sits inside.
            "우유, 계란, 빵 장보기 목록 만들어줘", "빨강, 파랑, 초록으로 버튼 색만 바꿔줘", "빨강, 파랑, 초록 버튼 만들어줘",
            "김철수, 이영희, 박민수 명단 만들어줘", "이름, 이메일, 전화번호 입력 화면 만들어줘", "아이디, 비밀번호, 이메일 가입 화면 만들어줘",
            "설정 페이지에 테마, 언어, 시간대 탭 추가해줘", "로그인, 회원가입, 검색 버튼 만들어줘", "커피, 케이크, 샌드위치 메뉴 만들어줘",
            "파이썬, 고, 러스트로 구현해줘", "이름, 나이, 주소 구현해줘", "빨래, 설거지, 청소 다 해줘",
            "make a grocery list with milk, eggs and bread", "add alice, bob and carol", "add name, email and phone validation",
            "add login, signup and search", "build login, signup and search buttons",
            # Targets, functions and things named under a verb that builds software.
            "build api, web and worker", "build linux, macos and windows", "build the api, web and worker images",
            "implement get, set and delete", "implement sin, cos and tan",
            # A range of numbers, pages, dates or positions; the other verbs; counted one thing.
            "1부터 10까지 더하는 함수 만들어줘", "1페이지부터 3페이지까지 요약해줘", "월요일부터 금요일까지 일정 알려줘", "서울부터 부산까지 몇 시간 걸려?",
            "처음부터 끝까지 만들어줘", "처음부터 끝까지 진행해", "아침부터 저녁까지 만들어줘", "로그인부터 결제까지 고쳐줘",
            "summarize pages 1 to 3", "rename the variable from foo to bar", "build a function that sums from 1 to 10",
            "build it from start to finish", "build it from monday to friday", "build from source to binary",
            "두 단계 인증 구현해줘", "세 페이지 보고서 만들어줘", "여러 페이지 PDF 만들어줘", "네 화면 만들어줘", "여러 기능이 안 돼",
            "several features are broken", "review multiple modules", "build several pages",
            # Comparisons, questions, one fix, stop words, later, and text of a request held in another one.
            "로그인, 목록, 알림 화면 차이 설명해줘", "검색, 필터, 정렬 중 어떤 걸 먼저 할까?", "사과, 배, 귤 중에 뭐가 제일 싸?",
            "로그인 버그 고쳐줘", "로그인, 목록, 알림 다 하지 마", "검색, 필터, 정렬 기능 나중에 붙여줘",
            "what is the difference between login, signup and sso?", "로그인, 회원가입, 검색 기능 리뷰해줘",
            "다음 문장을 교정해줘: 로그인, 회원가입, 검색 기능 만들어줘",
            # What has to happen, stated rather than asked; a range from a to z names no stage.
            "로그인, 회원가입, 검색 기능 만들어야 해", "회원가입부터 결제까지 만들어야 해", "build it from a to z",
            # An intent stated; product features on a bare 해; a range whose ends are not both product features.
            "로그인, 회원가입, 검색 기능 만들까 해", "로그인, 회원가입, 검색 기능 만들려고 해", "회원가입부터 결제까지 만들려고 해",
            "검색, 요약, 공유 다 해줘", "로그인, 목록, 알림 다 해줘", "회원가입부터 결제까지 다 해줘",
            "가을부터 겨울까지 만들어줘", "입문부터 심화까지 만들어줘", "데이터 수집부터 리포트 생성까지 만들어줘",
            "build it from dawn to dusk", "implement it from python to rust", "develop it from sign-up to the knowledge graph",
            "build research, borders and dashboards",
        ):
            with self.subTest(message=message):
                self.assertFalse(names_several_features(message))

    def test_several_features_reads_no_long_message(self) -> None:
        # A brief or a pasted log reads as on main, and adds nothing to what its length costs the other readers.
        request = "로그인, 회원가입, 검색 기능 만들어줘"
        self.assertTrue(names_several_features(request))
        self.assertFalse(names_several_features(" " * 1000 + request))

    def test_several_features_offer_is_the_same_on_a_host_without_the_package(self) -> None:
        # Hermes loads the bundle on its own interpreter: the offer and its absence read alike there.
        standalone = _load_standalone_bundle_awareness()
        for message in ("메일 가져오기, 파일 업로드, 검색 기능 개발해줘", "회원가입부터 결제까지 개발해줘", "build the upload, preview and download screens",
                        "빨강, 파랑, 초록 버튼 만들어줘", "build api, web and worker"):
            with self.subTest(message=message):
                self.assertEqual(
                    [hint.get("next_action") for hint in standalone.awareness_route_hint(message)["hints"]],
                    [hint.get("next_action") for hint in awareness_route_hint(message)["hints"]],
                )
                self.assertEqual(
                    standalone.awareness_route_hint(message)["selected_workflow"],
                    awareness_route_hint(message)["selected_workflow"],
                )

    def test_each_hard_exclude_alone_keeps_a_change_off_the_graph(self) -> None:
        # Each row is a change the router would dispatch on but for one hard exclude: a skill or engine named first
        # (with a Korean particle, in Korean, or after omh), a past, one pull request's scope (by number, in words or
        # as 풀리퀘), a stop or a hold, a completion, a condition, work until a condition, parallel running as the
        # work's subject, a recurring schedule, one branch (named or current), one PR singled out by a modifier.
        for message in ("team 열린 PR들 전부 리베이스해줘", "plan 모든 패키지 버전 올려줘", "PR들 전부 리베이스했으니 머지해줘",
                        "PR 2232 파일들 전부 고쳐줘", "fix all the files in this PR", "PR들 전부 리베이스 중단하고 머지해줘",
                        "브랜치들 다 정리됨 이제 전부 머지해줘", "테스트 다 통과하면 모든 PR 머지해줘",
                        "fix all the failing tests until CI is green", "fix all the modules that run in parallel",
                        "loop로 모든 서비스 업데이트해줘", "루프로 모든 서비스 업데이트해줘", "omh loop 모든 서비스 업데이트해줘",
                        "update all snapshots in PR number 2240", "2240번 풀리퀘 모든 테스트 다시 고쳐줘",
                        "테스트 수정 완료, 이제 PR들 전부 머지해줘", "rebase all my open PRs every hour", "매일 아침 PR들 전부 리베이스해줘",
                        "pull 951 테스트들 다 고쳐줘", "fix all the failing tests on feature/dag-default",
                        "fix all the failing tests on the current branch", "현재 브랜치 테스트 전부 고쳐줘", "어제 내가 연 PR 테스트 전부 고쳐줘",
                        # A PR number without a counter stays one scope, the numbered twins of "PR 3개".
                        "PR 3 테스트 전부 고쳐줘", "3번 PR 테스트 전부 고쳐줘", "#3 테스트 전부 고쳐줘",
                        # A schedule in its other shapes, and one PR picked out by an adjective (#2232 review 3).
                        "2시간에 한 번씩 레포들 전부 의존성 올려줘", "하루 두 번 열린 PR들 전부 리베이스해줘",
                        "rebase every open PR each morning", "격주로 모든 서비스 로그 포맷 고쳐줘", "cron으로 모든 서비스 업데이트해줘",
                        "주 2회 모든 패키지 업데이트해줘", "update all services twice a day", "스케줄 걸어서 모든 서비스 업데이트해줘",
                        "fix every test in my latest pull request",
                        # A noun with 마다 other than a unit of work, 매 + a noun, an interval, a clock word, every
                        # other day, an event that repeats the work, and one PR picked out by 하나 (#2232 review 4).
                        "반나절마다 PR들 전부 리베이스해줘", "스프린트마다 모든 패키지 올려줘", "배포마다 모든 서비스 설정 업데이트해줘",
                        "매 분기마다 모든 레포 라이선스 업데이트해줘", "매 스프린트 모든 패키지 올려줘", "3일 간격으로 모든 서비스 업데이트해줘",
                        "fix all failing tests on every push", "rebase all open PRs on each merge", "자정에 PR들 전부 리베이스해줘",
                        "하루 걸러 모든 서비스 업데이트해줘", "우리 팀 PR 하나 테스트 다 고쳐줘", "일정 간격으로 PR들 전부 리베이스해줘"):
            with self.subTest(message=message):
                self.assertFalse(dispatches_dag_ulw(message))
                router, hint, _candidate = self._dag_ulw_starts(message)
                self.assertFalse(router)
                self.assertFalse(hint)
        # A review is offered, never dispatched: the allow list holds only changes.
        self.assertFalse(dispatches_dag_ulw("PR들 전부 리뷰해줘"))
        self.assertTrue(work_over_many_targets("PR들 전부 리뷰해줘"))

    def test_a_skill_named_or_invoked_keeps_a_change_over_many_targets(self) -> None:
        # The name with a Korean particle, in Korean, after omh, or as the instrument anywhere, and an explicit
        # invocation of a skill or the loop, keep the request on that skill: the router does not dispatch dag-ulw and
        # the hint does not start it.
        for message, skill in (("loop로 모든 서비스 업데이트해줘", "loop"), ("루프로 모든 서비스 업데이트해줘", "loop"),
                               ("loop으로 PR들 전부 리베이스해줘", "loop"), ("omh loop 모든 서비스 업데이트해줘", "loop"),
                               ("github-event-ops로 열린 PR들 전부 리베이스해줘", "github-event-ops"),
                               ("github-event-ops에서 열린 PR들 전부 리베이스해줘", "github-event-ops"),
                               ("deploy-and-monitor로 모든 서비스 업데이트해줘", "deploy-and-monitor"),
                               ("git-workflow로 브랜치들 전부 리베이스해줘", "git-workflow"),
                               ("use git-workflow: 열린 PR들 전부 리베이스해줘", "git-workflow"),
                               ("rebase all my open PRs with git-workflow", "git-workflow")):
            with self.subTest(message=message):
                route = route_chat_message(message, source="discord")
                self.assertEqual((route["action"], route["selected_skill"]), ("dispatch", skill))
                self.assertEqual(self._dag_ulw_starts(message)[:2], (False, False))
        for message in ("team으로 모든 서비스 업데이트해줘", "ralph로 모든 서비스 업데이트해줘", "maestro로 모든 패키지 버전 올려줘",
                        "refactor-plan으로 모든 모듈 python 3.12로 올려줘", "refactor-plan를 써서 모든 모듈 python 3.12로 올려줘",
                        "code-review로 열린 PR들 전부 고쳐줘",
                        "열린 PR들 전부 git-workflow로 리베이스해줘", "모든 서비스 루프로 돌면서 업데이트해줘"):
            with self.subTest(message=message):
                self.assertFalse(dispatches_dag_ulw(message))
                self.assertEqual(self._dag_ulw_starts(message)[:2], (False, False))
        # The cue reads the change; the explicit invocation is what keeps it off the graph, on both surfaces.
        self.assertTrue(dispatches_dag_ulw("use git-workflow: 열린 PR들 전부 리베이스해줘"))

    def test_a_pull_request_link_is_one_scope(self) -> None:
        # The executable text leaves the link out, so the callers pass it: the PR it points at is one scope.
        message = "https://github.com/rlaope/oh-my-hermes/pull/2240 의 테스트 전부 고쳐줘"
        regions = reference_regions(message)
        self.assertTrue(dispatches_dag_ulw(regions.executable_text))
        self.assertFalse(dispatches_dag_ulw(regions.executable_text, regions.links))
        self.assertFalse(work_over_many_targets(regions.executable_text, regions.links))
        self.assertEqual(self._dag_ulw_starts(message)[:2], (False, False))

    def test_a_count_is_breadth_only_on_prs_repos_or_branches_with_a_breadth_word(self) -> None:
        # Lead decision on the #2232 review: "PR 3개 전부" and "PR 5개 다" are many PRs, while a count of anything else,
        # or a count with no breadth word, is a small single task that starts nothing, as on main.
        for message in ("PR 3개 전부 리베이스해줘", "PR 5개 다 머지해줘", "레포 3개 전부 의존성 올려줘", "브랜치 2개 모두 main에 리베이스해줘"):
            with self.subTest(message=message):
                self.assertEqual(self._dag_ulw_starts(message)[:2], (True, True))
        for message in ("파일 2개 수정해줘", "테스트 3개 고쳐줘", "파일 두 개 이름 바꿔줘", "이슈 2건 닫아줘", "PR 2개 머지해줘",
                        "엔드포인트 2개 인증 붙여줘", "서비스 세 개 node 22로 올려줘", "PR 3개 리베이스해줘", "파일 2개 전부 수정해줘",
                        "테스트 3개 다 고쳐줘", "서비스 세 개 다 업데이트해줘", "PR 3개 중 하나 리베이스해줘"):
            with self.subTest(message=message):
                self.assertFalse(dispatches_dag_ulw(message))
                self.assertFalse(work_over_many_targets(message))
                router, hint, candidate = self._dag_ulw_starts(message)
                self.assertEqual((router, hint), (False, False))
                self.assertNotEqual(candidate, "dag-ulw")

    def test_a_unit_of_work_with_madda_is_each_of_them_not_a_schedule(self) -> None:
        # "서비스마다" and "PR마다" mean each of them, so they route as they did before the schedule reader read 마다:
        # a breadth object with a change runs as a graph, and one with none starts nothing. Any other noun with 마다 is
        # a schedule (`test_each_hard_exclude_alone_keeps_a_change_off_the_graph`).
        for message in ("PR마다 테스트 전부 고쳐줘", "각 서비스마다 로깅 추가해줘"):
            with self.subTest(message=message):
                self.assertEqual(self._dag_ulw_starts(message)[:2], (True, True))
        for message in ("서비스마다 로깅 추가해줘", "레포마다 CI 설정 고쳐줘", "모듈마다 로거 붙여줘", "패키지마다 버전 올려줘"):
            with self.subTest(message=message):
                self.assertEqual(self._dag_ulw_starts(message)[:2], (False, False))

    def test_a_split_starts_only_where_the_router_dispatches_it(self) -> None:
        # Rule A for the size cues: named work asked to split into parallel parts dispatches dag-ulw on the router and
        # starts it in the hint; a split of text, a proposal, a plan said, a report, a question or breadth alone is
        # asked about on the router and offered in the hint, never started by the hint alone.
        for message in ("fan out across the services and migrate each one to the new logger",
                        "the migration is big, split it into parallel lanes", "결제, 주문, 배송 모듈을 병렬로 나눠서 리팩터링해줘",
                        "문장 분리기와 문단 파서 작업을 병렬로 나눠서 구현해줘", "can you split the api, ui and docs work into parallel lanes?",
                        "analyze API and UI in parallel, then integrate the findings",
                        "api, ui, docs 작업을 병렬로 나눠서 마이그레이션하고 결과 알려줘",
                        "tell me when done: split the api, ui and docs work into parallel lanes",
                        "결제, 주문, 배송 모듈을 병렬로 나눠서 리팩터링해줄래?", "api, ui, docs 작업을 병렬로 나눠서 구현해 주시겠어요?",
                        "api, ui, docs 작업을 병렬로 나눠서 구현해줄 수 있어?", "결제/주문/배송 모듈 병렬로 나눠서 리팩터링해줘",
                        "api, ui, docs 작업을 병렬로 나눠서 구현하고 어떻게 나눴는지 설명해줘", "이 api와 ui를 병렬로 나눠서 구현해줘",
                        "split the api and the ui into parallel lanes and implement them",
                        "split the migration into parallel lanes and verify each",
                        "split the billing services into parallel lanes and migrate each one",
                        # A count or 들 after a demonstrative is several objects; a topic said first that is several
                        # objects still runs; rewrite is a change; a report after a -고 work verb is the work's tail.
                        "이 세 서비스 병렬로 나눠서 마이그레이션해줘", "이 두 모듈 병렬로 나눠서 리팩터링해줘",
                        "이 3개 모듈 병렬로 나눠서 리팩터링해줘", "the api and ui work: split it into parallel lanes and implement them",
                        "split the parser and lexer modules into parallel lanes and rewrite them",
                        "결제, 정산 모듈 병렬로 나눠서 고치고 뭘 고쳤는지 보고해줘"):
            with self.subTest(message=message):
                self.assertTrue(dispatches_dag_ulw(message))
                self.assertEqual(self._dag_ulw_starts(message)[:2], (True, True))
        for message in ("split the paragraphs into parallel parts for translation", "문단 하나를 병렬로 나눠서 번역해줘",
                        "how about we fan out across the services and migrate each one",
                        "my plan is to split the api, ui and docs work into parallel lanes",
                        "fan out across the services and give each a one-sentence summary",
                        "which way should I split the work into parallel lanes", "split this into parallel tasks: lint, test, build",
                        "여러 모듈에 걸친 결제 기능 구현해줘", "why don't we split the api, ui and docs work into parallel lanes",
                        "maybe split the api, ui and docs work into parallel lanes", "split the translation work into parallel lanes",
                        # One named object split into parallel parts is one task (#2243 review).
                        "이 함수 병렬로 나눠서 구현해줘", "이 파일 병렬로 나눠서 수정해줘", "로그인 페이지 하나 병렬로 나눠서 고쳐줘",
                        "README 병렬로 나눠서 업데이트해줘", "이 스크립트를 병렬로 나눠서 개발해줘",
                        # One object said first as the topic the split refers back to, a rewrite of one object, and a
                        # report after a word with no work verb in it.
                        "the checkout page: split it into parallel parts and fix it",
                        "the login form: split it into parallel parts and fix it",
                        "split the paragraph parser into parallel lanes and rewrite it",
                        "결제, 정산 모듈 병렬로 나눠서 보고 뭘 고칠지 보고해줘"):
            with self.subTest(message=message):
                self.assertFalse(dispatches_dag_ulw(message))
                self.assertEqual(self._dag_ulw_starts(message)[:2], (False, False))
                offers = [hint for hint in awareness_route_hint(message)["hints"] if hint.get("workflow") == "dag-ulw"]
                self.assertEqual([hint.get("next_action") for hint in offers], ["ask_one_clarification"])
        # One named object with a fault to fix goes to the lane that fixes it, and starts no graph either.
        message = "fan out the image resize into parallel workers and fix the crash"
        self.assertFalse(dispatches_dag_ulw(message))
        self.assertEqual(self._dag_ulw_starts(message)[:2], (False, False))

    def test_a_request_taken_back_or_held_in_a_later_clause_starts_nothing(self) -> None:
        # A clause after the request keeps it only on positive evidence (#2243 review): a keeper or a follow-on with a
        # sequencing connective. Anything else after it, in Korean or English, leaves nothing to dispatch or start.
        for message in ("PR들 전부 리베이스해줘, 아 잠깐만", "모든 서비스 업데이트해줘, 아니 잠깐", "레포들 전부 CI 고쳐줘, 근데 일단 대기",
                        "레포들 전부 CI 고쳐줘, 말고 그냥 둬", "브랜치들 전부 리베이스해줘, 아니다 나중에 하자",
                        "모든 서비스 node 22로 올려줘, 는 다음 주에 하자", "모든 서비스 업데이트해줘, 는 농담이고",
                        "엔드포인트 전부 인증 붙여줘, 장난이야", "PR들 전부 머지해줘, 는 아니고 리뷰만 해줘", "PR들 전부 머지해줘, 같은 요청은 위험해",
                        "rebase all open PRs, never mind", "update every service — jk", "fix all the failing tests, scratch that",
                        "rebase all open PRs, or not", "update every service, actually don't", "fix all the failing tests, wait",
                        "PR들 전부 리베이스해줘, 음 아니야", "모든 서비스 업데이트해줘, 아냐 내가 할게", "레포들 전부 CI 고쳐줘, 아 이건 좀 아닌가",
                        "PR들 전부 머지해줘, 아 근데 잠시만", "rebase all open PRs, lol jk", "update every service — wait, no",
                        "fix all the failing tests... or maybe not", "rebase all open PRs or maybe not",
                        # A trailing remark that is no keeper and asks for no work keeps nothing either, listed or not:
                        # hesitation, worry, a question about the request, doubt or a side note.
                        "PR들 전부 머지해줘, 하고 싶은데 무서워", "모든 서비스 업데이트해줘, 해도 되나", "레포들 전부 CI 고쳐줘, 이거 맞아?",
                        "모든 서비스 업데이트해줘, 어떻게 생각해", "PR들 전부 리베이스해줘, 나중에 해줘", "모든 패키지 업데이트해줘, 근데 괜찮을까",
                        "브랜치들 전부 리베이스해줘, 팀장님이 시킨 거야", "모든 서비스 업데이트해줘, 잘 모르겠지만", "PR들 전부 리베이스해줘, 확신은 없어",
                        "모든 패키지 업데이트해줘, 좀 위험할 수도", "PR들 전부 머지해줘, 걱정되네",
                        "레포들 전부 CI 고쳐줘, 지난번에 이거 하다 CI 깨졌어",
                        "rebase all open PRs, what do you think",
                        "merge all open PRs, I'm scared though", "update every service, not sure", "rebase all open PRs, maybe tomorrow",
                        "update every service, is that ok?", "update every service, should I?", "rebase all open PRs, if that makes sense",
                        "update every service, is this right?", "update every service, not sure though",
                        "fix all the failing tests, is that safe", "rebase all open PRs, hmm, risky maybe",
                        "update every service, though I doubt it's worth it", "fix all the failing tests, fwiw last time this broke CI",
                        "update every service... not sure", "update every service, then we'll see",
                        # Work narrowed to itself alone, an undo, or work in place of the request keeps nothing.
                        "PR들 전부 리베이스해줘, 확인만 해줘", "PR들 전부 리베이스해줘, 리뷰만 해줘", "PR들 전부 리베이스해줘, 그냥 되돌려줘",
                        "PR들 전부 머지해줘, 는 아니고 리뷰해줘", "PR들 전부 머지해줘, 말고 리뷰해줘", "PR들 전부 머지해줘, 아니 리뷰해줘",
                        "PR들 전부 리베이스해줘, 그리고 확인만 해줘", "PR들 전부 머지해줘, 그 다음 되돌려줘",
                        # A follow-on keeps the request only after a sequencing connective, with no hold or joke in it or in
                        # a clause between, and only on more work: a bare follow-on or a report falls back.
                        "PR들 전부 리베이스해줘, 장난이고 테스트 돌려줘", "모든 서비스 업데이트해줘, 아 잠깐 다시 확인해줘",
                        "PR들 전부 머지해줘, 아니 잠깐, 로그 먼저 확인해줘", "브랜치들 전부 리베이스해줘, 아 그거 말고 테스트만 돌려줘",
                        "PR들 전부 머지해줘, 아니 잠깐, 그리고 로그 확인해줘", "PR들 전부 리베이스해줘, 그리고 농담이고 테스트 돌려줘",
                        "PR들 전부 리베이스해줘, 테스트 돌려줘", "모든 서비스 업데이트해줘, 확인해줘", "rebase all open PRs, run the tests",
                        "PR들 전부 리베이스해줘, 그리고 결과 알려줘", "모든 서비스 업데이트해줘, 끝나면 대시보드도 봐 줘",
                        # A confirmation tag keeps the request only as the message's last words; a colon list holds
                        # only items that open on a verb of work; a report tail keeps nothing that asks, sets a
                        # condition or holds; a per-unit spec keeps nothing that follows it.
                        "split the api, ui and docs work into parallel lanes, ok? actually no",
                        "rebase all my open PRs, ok? actually no", "is it ok to rebase all my open PRs?",
                        "rebase all my open PRs, ok? or not", "is it alright to update every service?",
                        "update every service, right? or should we wait",
                        "for each of my upstream PRs: rebase, then wait", "for each of my upstream PRs: rebase, not sure though",
                        "for each open PR: check, report, nothing else", "for each open PR: review, comment, don't merge",
                        "for each open PR: rebase, idk", "for each open PR: rebase, maybe later",
                        "for each of my upstream PRs: rebase, merge jk, push",
                        "for each of my upstream PRs: rebase, resolve conflicts, push, lol jk",
                        "migrate every package to pnpm, then tell me whether we even need to",
                        "rebase all open PRs, and let me know if I should",
                        "update every service, then tell me which one to start with?",
                        "fix all the failing tests, and ping me if it breaks", "fix all the failing tests, then ping me, never mind",
                        "update every service, one PR per service, not sure", "rebase all open PRs, one commit maybe",
                        # A tail that holds, is the person's own step, or asks for anything before the work or about
                        # whether to do it is no report on the result; every hard exclude reads the whole text.
                        "rebase all open PRs, then tell me why we shouldn't", "update every service, and let me check with the team first",
                        "migrate every package to pnpm, and let me get sign-off before anything",
                        "rebase all open PRs, then tell me the risks first",
                        "update every service, and tell me what would break before you do",
                        "fix all the failing tests, then show me how you would do it first",
                        "rebase all open PRs, and let me get sign-off from the team", "update every service, then let me run it by the team",
                        "bump all the packages, and let me think about it", "rebase all open PRs, then tell me which ones should be merged",
                        "update every service, then send me the list of risks first", "fix all the failing tests, then tell me if it's worth it",
                        "fix all the failing tests and tell me why we shouldn't",
                        "rebase all open PRs, then let me know which ones conflicted after the freeze",
                        "update every service, and send me the diff tomorrow",
                        "bump every package and let me know which ones break, jk",
                        "update every service and report any that fail?", "convert all the tests to pytest and tell me whether any fail",
                        # A deferral past now, in English or Korean, wherever it is said.
                        "rebase all the open PRs later, ok?", "rebase all the open PRs tomorrow, ok?", "update every service next week, ok?",
                        "update every service tonight, alright?", "rebase all open PRs on monday, okay?",
                        "fix all the failing tests later, right?", "bump every package eventually, ok?",
                        "migrate every package to pnpm some other time, ok?", "rebase all the open PRs tomorrow",
                        "update every service this weekend", "fix all the failing tests at some point",
                        "bump all the packages after the freeze", "update every service, tonight", "PR들 전부 나중에 리베이스해줘",
                        "모든 서비스 내일 업데이트해줘", "PR들 전부 다음 주에 리베이스해줘", "모든 패키지 언젠가 업데이트해줘",
                        "레포들 전부 주말에 CI 고쳐줘", "브랜치들 전부 월요일에 리베이스해줘",
                        "rebase all open PRs in a bit", "update every service in a while", "fix all the failing tests later on",
                        "bump all the packages down the line", "migrate every package to pnpm when I get a chance",
                        "rebase all the PRs I opened, tomorrow", "update every service we deployed, next week",
                        "rebase all the PRs I opened — tomorrow",
                        # A colon list ends at an item that opens on a status or a hedge, or carries one anywhere.
                        "for each open PR: rebase, squash, merge, too risky though",
                        "for every repo: bump deps, regenerate lockfiles, someday", "for each repo: bump deps, open PRs, eh, rather not",
                        "for all services: upgrade node, redeploy, someone else's call though",
                        "for each package: bump the version, publish, nope", "rebase all my open PRs: done, done, conflict",
                        "rebase all my open PRs: all done", "for each repo: bump deps, tested, shipped", "for each open PR: rebase, merge, ugh",
                        "for every service: upgrade node, redeploy, meh", "for each package: bump, publish, not my call",
                        "for each open PR: rebase, squash, maybe merge", "update every service: green, green, failed",
                        "for every repo: bump deps, lol", "update every service: the billing one first",
                        "rebase all open PRs, then tell me which ones failed and which you want to retry",
                        "update every service, then tell me which ones failed first",                        # A person subject with a modal or an intention, a bare infinitive, and a time ahead of now.
                        "rebase all open PRs, then tell me which ones you'd skip",
                        "update every service, and tell me every branch you plan to delete",
                        "rebase all open PRs, then tell me which ones we should keep",
                        "bump all the packages, and tell me any you want to leave",
                        "rebase all open PRs, then tell me which ones to keep",
                        "update every service, and tell me what to drop",
                        "rebase all open PRs, then tell me which ones you would skip",
                        "update every service, and tell me which ones they'll drop",
                        "update every service we deployed in 3 days", "rebase all open PRs in a few hours",
                        "모든 서비스 이따가 업데이트해줘", "rebase all the PRs we opened next friday",
                        "rebase all the PRs we opened, next friday",
                        # No report: a deliberation noun or verb, an infinitive, modal or intention after the quantifier, a bare quantifier, a when that is no completion; a time ahead of now after a past clause.
                        "rebase all open PRs, then tell me your reasons", "update every service, and send me any concerns",
                        "bump all the packages, then tell me your thoughts on it",
                        "migrate every package to pnpm, and let me know any objections",
                        "rebase all open PRs, then tell me the pros and cons",
                        "update every service, and tell me your approach",
                        "fix all the failing tests, and send me the alternatives",
                        "rebase all open PRs, then tell me what you think",
                        "update every service, and tell me which ones you'd recommend",
                        "rebase all open PRs, then tell me the ones to merge",
                        "update every service, and tell me which ones we should keep",
                        "bump all the packages, then tell me which ones you would drop",
                        "migrate every package to pnpm, and tell me what you'll change",
                        "rebase all open PRs, then tell me the ones we plan to close",
                        "update every service, and tell me which ones you want to skip",
                        "rebase all open PRs, then tell me which ones", "update every service, and tell me any",
                        "bump all the packages, then send me those",
                        "rebase all open PRs, and notify me when it's ready to merge",
                        "update every service, and ping me when you're about to deploy",
                        "bump all the packages, and tell me once we plan to land it",
                        "migrate every package to pnpm, and let me know when you have a plan",
                        "update every service, and tell me when you're going to start",
                        "rebase all the PRs we opened tomorrow", "update every service we deployed next week",
                        "fix all the tests that broke later", "rebase all the PRs we opened, tomorrow",
                        "update every service we shipped in a bit", "PR들 전부 배포한 거 내일 리베이스해줘", "모든 서비스 배포한 다음 주에 업데이트해줘",
                        "모든 패키지 업데이트한 나중에 다시 올려줘"):
            with self.subTest(message=message):
                self.assertFalse(dispatches_dag_ulw(message))
                self.assertEqual(self._dag_ulw_starts(message)[:2], (False, False))
        # Keepers by shape (an urgency or a deadline, a start cue, thanks or politeness, with an intensifier or a
        # request ending of their own) and a follow-on after a sequencing connective keep it.
        for message in ("모든 패키지 업데이트해줘, 패키지마다 changelog도 써줘", "모든 서비스 업데이트해줘, 그리고 CI도 고쳐줘",
                        "PR들 전부 리베이스해줘, 그 다음 테스트 돌려줘", "모든 서비스 업데이트해줘, 끝나고 문서도 정리해줘",
                        "PR들 전부 리베이스해줘, 그리고 결과 리포트 써줘", "모든 패키지 업데이트해줘, 다음으로 CI 다시 실행해줘",
                        "레포들 전부 CI 고쳐줘, 그리고 README도 갱신해줘", "모든 서비스 업데이트해줘, 급해, 그리고 CI도 고쳐줘",
                        "rebase all open PRs, then run the tests", "fix all the failing tests, and then rebase all open PRs",
                        "PR들 전부 리베이스해줘, 급해", "PR들 전부 리베이스해줘, 급함", "PR들 전부 리베이스해줘, 급합니다",
                        "모든 서비스 업데이트해줘, 빨리", "모든 서비스 업데이트해줘, 얼른", "모든 서비스 업데이트해줘, 최대한 빨리",
                        "모든 패키지 업데이트해줘, 서둘러줘", "PR들 전부 리베이스해줘, 가능한 빨리 부탁드려요",
                        "모든 서비스 업데이트해줘, 오늘 안에", "PR들 전부 리베이스해줘, 내일까지", "모든 패키지 업데이트해줘, 이번 주 안에",
                        "모든 서비스 업데이트해줘, 금요일까지", "PR들 전부 리베이스해줘, 오늘까지는", "모든 서비스 업데이트해줘, 내일 오전까지",
                        "모든 서비스 업데이트해줘, 부탁해", "모든 서비스 업데이트해줘, 부탁드려요", "PR들 전부 리베이스해줘, 부탁할게",
                        "PR들 전부 리베이스해줘, 고마워", "PR들 전부 리베이스해줘, 고맙다", "PR들 전부 리베이스해줘, 감사",
                        "모든 서비스 업데이트해줘, 감사합니다", "PR들 전부 리베이스해줘, 바로 시작해", "PR들 전부 리베이스해줘, 지금 바로",
                        "모든 서비스 업데이트해줘, 당장", "PR들 전부 리베이스해줘, 가자", "모든 서비스 업데이트해줘, ㄱㄱ",
                        "rebase all open PRs, asap", "rebase all open PRs by EOD", "update every service today",
                        "update every service, please", "fix all the failing tests, thanks", "fix all the failing tests, thank you",
                        "rebase all open PRs, go", "rebase all open PRs, by friday please", "update every service, urgently",
                        "fix all the failing tests, right away", "rebase all open PRs, no rush", "update every service, go ahead",
                        "fix all the failing tests, let's go", "rebase all open PRs, cheers", "update every service, ty",
                        "fix all the failing tests, appreciated", "rebase all open PRs, right now",
                        "fix all the failing tests, my boss asked",
                        # A plain report tail on the work, a final confirmation tag on any request, a colon list whose
                        # items each open on a verb of work, and a per-unit spec with any nouns, by shape.
                        "migrate every package to pnpm, then ping me with the results",
                        "migrate every package to pnpm, then tell me which ones conflicted",
                        "rebase all open PRs, and notify me when it's done",
                        "update every service to node 22, and then send me the diff summary",
                        "fix all the failing tests, then let me know which ones were flaky",
                        "upgrade all packages, and message me once they're merged",
                        "split the api, ui and docs work into parallel lanes, ok?", "rebase all my open PRs, ok?",
                        "update every service to node 22, okay?", "fix all the failing tests, alright?",
                        "migrate every package to pnpm, right?", "upgrade all modules to the new api, ok?",
                        "for each of my upstream PRs: rebase, resolve conflicts, push", "for each open PR: rebase, squash, merge",
                        "for every repo: bump the version, tag, deploy", "for each package: upgrade, rebuild, publish",
                        "for all services: rename the logger, re-run codegen, push",
                        "update every service, one PR per service", "bump all the packages, one commit per package",
                        "update every repo's CI config, a separate PR per repo",
                        "migrate every package to pnpm, a single changelog entry per package",
                        "fix all the failing tests, one branch for each module",
                        "update every service, each in its own branch", "rebase all open PRs, per repo",
                        # A report on the result by its positive shapes, and a deadline, which is no deferral.
                        "update every service, and send me the diff", "rebase all open PRs, and let me know",
                        "bump all the packages, and let me know once they're all merged",
                        "fix all the failing tests and report which ones were flaky", "rebase all my open PRs, then send me the links",
                        "update every repo's CI config, and tell me which ones changed", "update every service by tonight",
                        "rebase all open PRs, by friday", "rebase all open PRs now", "모든 서비스 업데이트해줘, 다음 주 월요일까지",
                        "update all services and report back",
                        # A report tail by its opening, any words after it, and a time inside a clause with a past verb
                        # of its own, which is no deferral.
                        "update every service to node 22 and report any that fail", "bump every package and let me know which ones break",
                        "convert all the tests to pytest and send me the ones that fail",
                        "upgrade every service to node 22 and report the ones that error out",
                        "convert all the tests to pytest, and show me the ones that failed",
                        "rebase all open PRs and tell me each one that needs a manual fix",
                        "migrate every package to pnpm, then ping me about anything that looks off",
                        "update every repo's CI config and send me those that still go red",
                        "fix all the failing tests, and tell me every one that stays flaky",
                        "bump all the packages and notify me after the last one lands",
                        "upgrade every service and ping me once the last one is merged",
                        "update every service we deployed on monday", "rebase all the PRs that failed yesterday",
                        "rebase all the PRs we opened on monday", "update every service we shipped over the weekend",
                        "월요일에 배포한 서비스 전부 업데이트해줘", "지난 월요일에 배포한 서비스 전부 업데이트해줘",
                        # The targets as the subject take any finite verb; a person with a plain verb reports.
                        "upgrade every package, then tell me which ones can't be upgraded",
                        "bump all the packages, and tell me any that won't build",
                        "rebase all open PRs, and tell me every package that needs to be rebuilt",
                        "rebase all open PRs, then tell me the ones that couldn't merge",
                        "update every service to node 22, and tell me which ones will break",
                        "migrate every package to pnpm, then tell me the ones you changed",
                        "update every service, and send me every file we touched",
                        "fix all the failing tests, then tell me which ones I broke",
                        "migrate every package to pnpm, then tell me what changed",
                        # Report tails by follower shape and a weekday inside a past clause.
                        "update every service to node 22 and report any that fail",
                        "bump every package and let me know which ones break",
                        "convert all the tests to pytest and send me the ones that fail",
                        "upgrade every service to node 22 and report the ones that error out",
                        "convert all the tests to pytest, and show me the ones that failed",
                        "rebase all open PRs and tell me each one that needs a manual fix",
                        "update every repo's CI config and send me those that still go red",
                        "fix all the failing tests, and tell me every one that stays flaky",
                        "migrate every package to pnpm, then tell me which files changed",
                        "rebase all open PRs, then tell me which ones conflict",
                        "bump all the packages and tell me all the failures",
                        "update every service, and send me the errors",
                        "bump all the packages and notify me after the last one lands",
                        "upgrade every service and ping me once the last one is merged",
                        "rebase all open PRs, and notify me when it's done",
                        "update every service and let me know once they're all merged",
                        "update every service, and let me know", "update all services and report back",
                        "rebase all open PRs, then send me the links", "update every service we deployed on monday",
                        "월요일에 배포한 서비스 전부 업데이트해줘", "rebase all the PRs we opened over the weekend"):
            with self.subTest(message=message):
                self.assertTrue(dispatches_dag_ulw(message))
                self.assertEqual(self._dag_ulw_starts(message)[:2], (True, True))

    def test_a_trailing_remark_keeps_the_request_only_by_kind(self) -> None:
        # After an English request, a trailing remark keeps it only when it is of a keep kind, in any words and with
        # any intensifier; a refusal class applies first, and an unknown remark holds (#2243 review, lead decision
        # (D)). Router and hint read the same, on work over many targets and on a split.
        kinds = {
            "gratitude": ("thanks a bunch", "thx so much!!", "much obliged", "I'd appreciate it", "you're the best",
                          "you rock, seriously!!", "bear with me"),
            "sign-off": ("have a good one", "talk soon", "regards", "catch you later", "later gators", "see ya", "take care"),
            "wish": ("fingers crossed", "really hope it goes smoothly", "hope it lands cleanly", "wish me luck", "good luck",
                     "hope there are no conflicts", "let's hope it sticks", "would love a clean run",
                     "got a good feeling about this one", "here's to a clean run", "may the build be green"),
            "back-reference": ("as discussed", "like we agreed", "same as last time", "per our chat",
                               "same deal as before", "following the plan from last sprint", "consistent with the RFC",
                               "like we did for billing"),
            "attribution": ("my manager asked for it", "legal approved it", "the PM requested this", "approved by the CTO",
                            "boss said go for it", "the PM's request", "it's for the audit", "at the request of QA",
                            "for the release team", "on behalf of legal"),
            "aside": ("fwiw the tests are flaky", "btw, CI is slow today", "also, the new keyboard is lovely",
                      "off topic, the new sofa arrived", "random but my cat just sneezed",
                      "on another note, the release notes look great", "incidentally the build cache is warm"),
            "no pressure": ("no worries", "no rush at all", "take your time", "whenever works", "not urgent",
                            "nothing pressing about it", "no deadline"),
        }
        # Each refusal shares its clause with a keep kind, so the class alone holds it.
        refusals = ("run the tests too thanks",  # a new request
                    "haha jk thanks",  # a hold or a joke
                    "btw lol",  # only a laugh
                    "fyi all done",  # only a status
                    "btw umm",  # only a hesitation
                    "thanks but the billing one first",  # something before the work
                    "btw this could break prod",  # a warning
                    "fwiw last time this broke CI",  # a warning
                    "thanks but still deciding",  # a hedge
                    "btw just spitballing",  # thinking aloud
                    "thanks but forget I said that",  # a retraction
                    "thanks but your call",  # the decision handed back
                    "no rush bin it",  # a verb on the request itself
                    "thanks and thoughts welcome",  # deliberation
                    "thanks we'll see",  # a person's modal
                    "can we do both thanks",  # a question
                    "thanks not yet",  # a negation
                    "oh and scrap that",  # a retraction after an aside marker
                    "side note, I'm cancelling that",  # a retraction by its stem
                    "thanks but need to confirm with legal",  # a precondition before the work
                    "part of me says go for it",  # a hedge, though someone says
                    "also, fix the lint")  # a new request after an aside marker, read by the follow-on rule
        unknown = ("long day lol", "peace")
        for work in ("rebase all open PRs", "update every service to node 22", "split the migration into parallel lanes"):
            for kind, tails in kinds.items():
                for tail in tails:
                    with self.subTest(kind=kind, message=f"{work}, {tail}"):
                        self.assertTrue(dispatches_dag_ulw(f"{work}, {tail}"))
                        self.assertEqual(self._dag_ulw_starts(f"{work}, {tail}")[:2], (True, True))
            for tail in (*refusals, *unknown):
                with self.subTest(message=f"{work}, {tail}"):
                    self.assertFalse(dispatches_dag_ulw(f"{work}, {tail}"))
                    self.assertEqual(self._dag_ulw_starts(f"{work}, {tail}")[:2], (False, False))
        # Adversarial twins: a refusal dressed in a keep kind's own stem holds, the refusal check running first,
        # whichever kind it borrows (#2243 follow-up).
        twins = ("boss said hold off", "approved by the CTO but not yet", "legal is fine with it but hold on",
                 "this came from the client, cancel it", "it's for the audit, so hold off", "on behalf of legal, hold off",
                 "at the request of QA, cancel that", "for the security team, but not yet", "Sam's request, but let's wait",
                 "like we agreed, scrap it", "like we hashed out, hold off for now", "same as the earlier convo, never mind",
                 "consistent with the RFC, but scrap it", "like we did for billing, not yet",
                 "fingers crossed but let's not", "keeping my toes crossed but let's wait",
                 "here's to a clean run but let's not", "may the build be green, but wait",
                 "may it be green but I am backing out", "hope it lands but I would rather wait",
                 "not in a hurry, actually don't", "whatever pace works, actually forget it",
                 "no deadline, but don't start yet", "bear with me, not sure yet", "you rock, seriously, but scratch that",
                 "also, I am calling it off", "side note, I'm calling the whole thing off", "fyi backing out of this",
                 "side note, I'm cancelling that",
                 "need to confirm it's safe on my side")
        for tail in twins:
            with self.subTest(message=f"rebase all open PRs, {tail}"):
                self.assertFalse(dispatches_dag_ulw(f"rebase all open PRs, {tail}"))
                self.assertEqual(self._dag_ulw_starts(f"rebase all open PRs, {tail}")[:2], (False, False))
        # A keep kind whose opener carries a statement (a toast or a wish, a back-reference, an attribution) keeps only
        # when the statement is clean: the refusal classes run on the statement too, and negating or abandoning the work
        # is refused even inside a wish (#2265 review).
        for tail in ("here's to not doing it", "here's to not bothering", "here's to leaving it alone",
                     "cheers to not touching it", "cheers to just letting it be", "hope we just leave it be",
                     "as discussed we're leaving it as is", "legal's request: leave it alone", "may we never touch it again",
                     "as we discussed we're not doing it", "on behalf of legal, leave it be",
                     # a statement set off by a colon is read on its own, as an aside's is
                     "fingers crossed: bin it", "as discussed: is that ok", "the PM's request: run the full suite",
                     # a negation of doing the work, in a keep kind
                     "thanks but let's not", "cheers don't bother", "thanks we won't need to", "fwiw we're not doing this",
                     "legal asked us not to", "thanks hold off", "thanks but no", "cheers I don't want it anymore",
                     "here's to letting sleeping services lie", "the team lead asked us to leave it",
                     "hope we leave it as is for now",
                     # a precondition not yet met, and a hedge on certainty
                     "fyi, I haven't cleared this with anyone yet", "thanks, not entirely certain it's needed",
                     "btw we haven't heard back yet", "fyi I haven't checked with legal"):
            with self.subTest(message=f"rebase all open PRs, {tail}"):
                self.assertFalse(dispatches_dag_ulw(f"rebase all open PRs, {tail}"))
                self.assertEqual(self._dag_ulw_starts(f"rebase all open PRs, {tail}")[:2], (False, False))
        for tail in ("here's to a green build", "cheers to a clean rebase", "may it merge cleanly", "hope it merges",
                     "hope there are no conflicts", "legal's fine with it", "agreed in standup",
                     # a negated outcome, side effect or constraint keeps
                     "hope nothing breaks", "fwiw no exceptions", "btw it won't touch prod", "here's to no more confusion",
                     # leaving it better, running, to someone or with a note is no abandoning
                     "hope we leave it better than we found it", "hope we leave a note in the changelog",
                     "fingers crossed we leave it running green", "hope they leave it to me",
                     # a retraction stem under a negation takes nothing back
                     "fyi no cancelling halfway"):
            with self.subTest(message=f"rebase all open PRs, {tail}"):
                self.assertTrue(dispatches_dag_ulw(f"rebase all open PRs, {tail}"))
                self.assertEqual(self._dag_ulw_starts(f"rebase all open PRs, {tail}")[:2], (True, True))
        # A "don't" or "do not" that governs a work verb asks for no work, before the remark gate; one that negates an
        # outcome (the outcome verbs `_NOT_DOING` excepts) does not, on the router and the hint alike (#2265 review).
        for tail in ("fingers crossed we don't regress", "hope we don't break imports", "hope this doesn't crash anything",
                     "here's to not breaking prod", "hope we are not losing data"):
            with self.subTest(message=f"rebase all open PRs, {tail}"):
                self.assertTrue(dispatches_dag_ulw(f"rebase all open PRs, {tail}"))
                self.assertEqual(self._dag_ulw_starts(f"rebase all open PRs, {tail}")[:2], (True, True))
        for tail in ("fyi don't skip any", "don't update every module", "don't touch it"):
            with self.subTest(message=f"rebase all open PRs, {tail}"):
                self.assertFalse(dispatches_dag_ulw(f"rebase all open PRs, {tail}"))
                self.assertEqual(self._dag_ulw_starts(f"rebase all open PRs, {tail}")[:2], (False, False))
        # The same on the size-cue path: the router and the hint agree on a negated outcome and on a negated work verb.
        work = "implement the export in parallel across the api and ui modules"
        self.assertEqual(self._dag_ulw_starts(f"{work}, hope we don't break imports")[:2], (True, True))
        self.assertEqual(self._dag_ulw_starts(f"{work}, don't touch the cli module")[:2], (False, False))
        # Reported speech carries its object: a third party saying no holds, and saying go, yes or fine keeps.
        for tail in ("ops said no", "legal said absolutely not", "boss said not a chance", "QA says no way",
                     "security said hard pass", "the team said count me out", "the client wants none of it",
                     "the lead told us no", "my manager asked: no", "btw, no"):
            with self.subTest(message=f"rebase all open PRs, {tail}"):
                self.assertFalse(dispatches_dag_ulw(f"rebase all open PRs, {tail}"))
                self.assertEqual(self._dag_ulw_starts(f"rebase all open PRs, {tail}")[:2], (False, False))
        for tail in ("ops said go", "the lead said it's fine", "legal said yes"):
            with self.subTest(message=f"rebase all open PRs, {tail}"):
                self.assertEqual(self._dag_ulw_starts(f"rebase all open PRs, {tail}")[:2], (True, True))
        # Reported speech keeps only when what was said is an approval, in any words and with any intensifier; any other
        # reported object holds, a refusal however it is put and anything unknown alike (#2265 review).
        for tail in ("QA says hard no", "legal said a firm no", "ops said heck no", "the lead said over my dead body",
                     "security said meh", "the client wants nothing to do with it", "the lead told us to sit on it",
                     "ops said something about the docs", "fyi the lead said meh"):
            with self.subTest(message=f"rebase all open PRs, {tail}"):
                self.assertFalse(dispatches_dag_ulw(f"rebase all open PRs, {tail}"))
                self.assertEqual(self._dag_ulw_starts(f"rebase all open PRs, {tail}")[:2], (False, False))
        for tail in ("legal said a big yes", "ops says totally fine", "the lead said go ahead", "the PM said ship it",
                     "QA said LGTM", "the team says we're clear", "the client wants it done", "security says she's on board",
                     "the boss gave the green light", "boss said go for it", "the team wants this",
                     "the lead told us to go ahead", "my manager asked for it", "like the ticket says",
                     "as we said we split by module"):
            with self.subTest(message=f"rebase all open PRs, {tail}"):
                self.assertEqual(self._dag_ulw_starts(f"rebase all open PRs, {tail}")[:2], (True, True))
        # The approval has to be the whole reported object, read on past a comma: sarcasm that wraps an approval word
        # holds, and a clean approval with intensifiers, filler and punctuation around it keeps (#2265 review).
        for tail in ("the lead said yeah right", "ops said sure, in your dreams", "QA said great idea… not",
                     "the lead said oh totally lol no", "legal said in your dreams", "the lead said it's not fine",
                     "ops said sure, good luck with that", "the PM said yes /s", "QA said lgtm... said no one",
                     "fyi the lead said sure, in your dreams", "the lead said, sure, in your dreams", "the PM said sure 🙄",
                     "the lead said ok?"):
            with self.subTest(message=f"rebase all open PRs, {tail}"):
                self.assertFalse(dispatches_dag_ulw(f"rebase all open PRs, {tail}"))
                self.assertEqual(self._dag_ulw_starts(f"rebase all open PRs, {tail}")[:2], (False, False))
        for tail in ("legal said a firm yes", "ops says totally fine!", "the lead said absolutely, go for it",
                     "QA said yes, absolutely", "ops said ok, ship it", "the lead said definitely, ship it",
                     "the lead said, go ahead", "btw ops said go ahead", "the lead said go ahead, then also bump the version",
                     # "that" before the object, and an infinitive's subject (#2265 review32).
                     "the PM said that's fine", "QA said that it's fine", "ops wants us to go ahead",
                     "the lead wants them to ship it"):
            with self.subTest(message=f"rebase all open PRs, {tail}"):
                self.assertEqual(self._dag_ulw_starts(f"rebase all open PRs, {tail}")[:2], (True, True))
        # An approval dressed in filler or said twice is sarcasm and holds, and so does a lone k (#2265 review32).
        for tail in ("the lead said oh yes, totally", "the lead said oh sure", "ops said well, ok", "QA said um, sure",
                     "the PM said sure, sure", "QA said yeah yeah", "the lead said yeah, sure", "ops said ok, sure, totally",
                     "the lead said cool cool", "legal said k", "fyi the lead said oh sure", "btw ops said yeah yeah"):
            with self.subTest(message=f"rebase all open PRs, {tail}"):
                self.assertFalse(dispatches_dag_ulw(f"rebase all open PRs, {tail}"))
                self.assertEqual(self._dag_ulw_starts(f"rebase all open PRs, {tail}")[:2], (False, False))
        # A negator before the reporting or approving verb holds whatever was said, on the router and the hint together,
        # a size-cue base included (#2265 review32).
        for message in ("rebase all open PRs, nobody said yes", "rebase all open PRs, not one of them said go",
                        "update every service to node 22, neither of them said yes", "rebase all open PRs, no-one said ship it",
                        "rebase all open PRs, ops never said go", "rebase all open PRs, the client never wanted it done",
                        "rebase all open PRs, nobody's said go", "rebase all open PRs, none of the leads approved it",
                        "rebase all open PRs, not a single reviewer signed off", "rebase all open PRs, nobody gave the green light",
                        "rebase all open PRs, no one has approved this", "rebase all open PRs, fyi nobody said yes",
                        "lint every module and fix the warnings, nobody said yes",
                        "lint every module and fix the warnings, nobody approved it",
                        "fix every flaky test across all packages, nobody signed off"):
            with self.subTest(message=message):
                self.assertFalse(dispatches_dag_ulw(message))
                self.assertEqual(self._dag_ulw_starts(message)[:2], (False, False))
        # A subordinating condition opener holds, trailing or leading; an urgency that borrows its words keeps (#2265
        # review32).
        for message in ("rebase all open PRs, assuming QA says it's fine", "rebase all open PRs, provided the CTO says ok",
                        "rebase all open PRs, as soon as the lead says go", "rebase all open PRs, so long as the build is green",
                        "rebase all open PRs, supposing legal agrees", "rebase all open PRs, in case the CTO approves",
                        "rebase all open PRs, on condition that QA signs off", "assuming QA is happy, rebase all open PRs",
                        "as long as CI is green, update every service to node 22"):
            with self.subTest(message=message):
                self.assertFalse(dispatches_dag_ulw(message))
                self.assertEqual(self._dag_ulw_starts(message)[:2], (False, False))
        for message in ("rebase all open PRs as soon as possible", "fix all the failing tests provided by QA",
                        # Only where it opens a clause: an adjective or a participle, and a constraint inside the clause,
                        # keep as on main (#2265 review33).
                        "add pagination to every list endpoint using the provided helper",
                        "update every service to node 22 with the provided config",
                        "rename every module per the provided naming guide", "fix all the failing tests with the fixtures provided",
                        "rebase all open PRs onto the branch provided", "bump every package with the provided changelog template",
                        "update all services to the provided base image", "close all stale issues using the provided label",
                        "update every service with the values provided",
                        "rename every module as long as the import paths stay the same",
                        "update every service assuming the defaults are fine"):
            with self.subTest(message=message):
                self.assertEqual(self._dag_ulw_starts(message)[:2], (True, True))
        for message in ("rebase all open PRs; supposing legal agrees", "rebase all open PRs — in case the CTO approves",
                        "rebase all open PRs: as soon as the lead says go",
                        "update every service to node 22 provided that the tests pass"):
            with self.subTest(message=message):
                self.assertFalse(dispatches_dag_ulw(message))
                self.assertEqual(self._dag_ulw_starts(message)[:2], (False, False))
        # The reported object is read by the kinds a bare remark is: thanks, a greeting, a sign-off or a wish keeps, an
        # approval keeps with when or what for, a plain statement keeps after an aside marker, and a relative what is no
        # reported speech (#2265 review32).
        for tail in ("the lead said thanks a ton", "the CTO said cheers", "the PM said have a great weekend",
                     "the client says hello", "the lead said best of luck", "the lead says fingers crossed",
                     "the client wants it by friday", "ops wants it by end of week", "the PM wants this this sprint",
                     "the lead wants it done in Q3", "ops said yes for the release", "legal says yes by eod",
                     "fwiw QA says the suite is faster now", "btw the PM said she'll review it",
                     "ps the client said the demo went well", "hope it's what the PM wants", "hope this is what legal wanted",
                     # #2265 review33: a plain aside statement, a clean wish, a single assent, and an attribution unnegated.
                     "btw ops says the new cluster is up", "fwiw legal says the contract is signed",
                     "fwiw QA said the flaky suite is fixed now", "btw the CTO said the budget isn't an issue",
                     "the PM said best of luck!", "ops said fingers crossed", "the lead said hope it goes well",
                     "QA said hope the rollout is smooth", "the CTO said good luck with the migration", "QA said great",
                     "the PM said nice", "the lead said perfect", "ops said cool, ship it", "the team gave the go-ahead",
                     "security cleared it",
                     # #2265 review34: a work item with a status word that is also good news, a negated problem or
                     # outcome, and thanks for something.
                     "btw ops says the fix is out", "btw ops says hotfix is out", "fwiw QA said the old ticket is closed",
                     "fyi the release is out",
                     "btw QA says the bug is gone", "btw the PM says the migration is done", "fyi ops said the error rate is down",
                     "btw QA says flakiness is down", "btw ops says the hotfix is out", "fyi QA said the alert is off",
                     "btw the lead says latency is down", "fwiw QA says it isn't a problem", "btw ops says it won't break anything",
                     "fwiw ops says it doesn't conflict with anything", "fyi QA said the flaky test isn't failing anymore",
                     "btw legal says it's not an issue", "fwiw ops said it wasn't urgent anyway", "thanks for the help",
                     "cheers for sorting it", "thanks for everything", "thanks for not breaking prod"):
            with self.subTest(message=f"rebase all open PRs, {tail}"):
                self.assertEqual(self._dag_ulw_starts(f"rebase all open PRs, {tail}")[:2], (True, True))
        for tail in ("btw the lead said idk", "fyi QA said not sure", "ps the PM said she's skeptical",
                     "the lead said thanks but no", "fyi ops said we should wait", "the lead said whatever",
                     "fyi the lead said thanks for nothing", "btw the PM said in your dreams",
                     "fyi the lead said over my dead body", "the client wants it next week",
                     # a refusal in a later part of the object, and a word after an approval that is no punctuation
                     "btw QA said the suite is green, but let's not merge yet", "fyi the PM said she'll review it, maybe",
                     "the PM said sure 🤡", "ops said fine 😬",
                     # Under an aside, a reported negated state, reluctance or blocking status holds; a reported wish
                     # holds unless it is a wish alone or that the work goes well; a doubled assent is no thanks; and a
                     # negated subject with a phrase after it, or a negator before an attribution verb, holds (#2265
                     # review33).
                     "btw legal says the contract isn't signed", "fwiw the CTO said she'd rather we didn't",
                     "btw ops says staging isn't ready", "fyi legal said the release wasn't approved",
                     "fwiw the lead said she would rather we waited", "btw ops says prod is frozen",
                     "fyi QA said the pipeline is blocked", "btw the CTO says the repo is locked down",
                     "btw finance says we're over budget", "fyi the lead said she's out today", "btw ops says the cluster is down",
                     "fyi legal says deploys are paused", "the PM said good luck lol", "ops said hope you enjoy debugging",
                     "legal said best of luck explaining that", "QA said fingers crossed you know what you're doing",
                     "the CTO said good luck haha", "fyi the PM said good luck lol", "QA said great, great",
                     "the PM said nice, nice", "QA said perfect, perfect", "no one on the team gave the go-ahead",
                     "not a soul signed off", "no one on security cleared it", "nobody from legal approved it",
                     "no-one gave the nod", "the team never gave the go-ahead", "no one on the team asked for this",
                     "not a soul asked for it", "no-one asked for it", "nobody in legal requested it", "the team never okayed it",
                     "security never greenlit it", "security has not blessed it", "none of the leads asked for this",
                     "not a single person requested it", "neither of them asked for it",
                     # A status word that is also good news holds with a person away or a system down; a blocking
                     # status, any negated state but a negated problem, reluctance and thanks for a negation hold
                     # (#2265 review34).
                     "btw ops says sarah is out", "fwiw the PM said he is off this week", "btw QA says the reviewer is away",
                     "fyi they said the oncall is sick", "fwiw QA says staging is offline", "btw the lead says main is locked",
                     "fwiw ops says the db is down", "btw ops says the build server is down", "fyi QA said CI is down",
                     "btw the PM said the launch is paused", "btw ops says staging isn't up",
                     "fyi the CFO said the budget isn't there", "fwiw QA says the suite doesn't pass",
                     "btw legal says the contract hasn't come back", "fyi ops said the cert won't renew in time",
                     "btw QA says CI can't keep up", "fwiw the lead said the design isn't final",
                     "btw the lead said he'd sooner we didn't", "fwiw the PM said she'd sooner we waited",
                     "thanks for nothing", "cheers for nothing", "thanks for nothing, really", "thx for no help",
                     "ty for nothing lol", "thanks a lot for nothing", "ta for none of it"):
            with self.subTest(message=f"rebase all open PRs, {tail}"):
                self.assertFalse(dispatches_dag_ulw(f"rebase all open PRs, {tail}"))
                self.assertEqual(self._dag_ulw_starts(f"rebase all open PRs, {tail}")[:2], (False, False))
        # A remark after a colon list's last item goes through the same gate: a status in either order holds, and a
        # dismissal holds.
        for message in ("for each open PR: rebase, merge, merged already", "for each open PR: rebase, merge, already merged",
                        "for each open PR: rebase, merge, not my problem",
                        "for each repo: bump deps, tested locally, shipped to staging"):
            with self.subTest(message=message):
                self.assertFalse(dispatches_dag_ulw(message))
                self.assertEqual(self._dag_ulw_starts(message)[:2], (False, False))
        self.assertEqual(self._dag_ulw_starts("for each open PR: rebase, squash, merge, thanks a ton")[:2], (True, True))
        # A follow-on after an aside marker keeps the request, as the follow-on rule does anywhere.
        self.assertEqual(self._dag_ulw_starts("rebase all open PRs, also, then run the tests")[:2], (True, True))

    def test_the_router_size_cue_follows_the_cue_readers_refusals(self) -> None:
        # The router's size-cue path dispatches dag-ulw only where the cue reader would start: a held, deferred or
        # asking request is asked about on the router and never started by the hint (#2243 review).
        for message in ("refactor the logging in all modules in parallel, then tell me which ones you'd skip",
                        "refactor the logging in all modules in parallel, then tell me which ones to keep",
                        "rewrite the error handling across all services in parallel, then tell me which ones we should keep",
                        "refactor the logging in all modules in parallel, and notify me when it's ready to merge",
                        "refactor the logging in all modules in parallel, then send me your misgivings",
                        "refactor the logging in all modules in parallel next week",
                        "refactor the logging in all modules in parallel, next week",
                        "모든 모듈의 로깅을 병렬로 리팩터링해줘 다음 주에"):
            with self.subTest(message=message):
                self.assertTrue(refuses_dag_ulw(message))
                self.assertEqual(self._dag_ulw_starts(message)[:2], (False, False))
        # A fault said in the past is no past when the message ends asking to fix it; a report, a question or a hold
        # after the fault keeps it held, and another past stays one.
        self.assertFalse(refuses_dag_ulw("api 모듈과 ui 모듈 테스트가 깨졌어, 동시에 고쳐줘"))
        self.assertTrue(self._dag_ulw_starts("api 모듈과 ui 모듈 테스트가 깨졌어, 동시에 고쳐줘")[0])
        for message in ("api 모듈과 ui 모듈 테스트가 깨졌어", "api 모듈과 ui 모듈 테스트가 깨졌어, 왜 그래?",
                        "api 모듈과 ui 모듈 테스트가 깨졌어, 아직 고치지 마", "모든 서비스 배포했어, 이제 다 업데이트해줘"):
            with self.subTest(message=message):
                self.assertTrue(refuses_dag_ulw(message))
                self.assertEqual(self._dag_ulw_starts(message)[:2], (False, False))
        # With nothing refused, the size cue still dispatches.
        message = "refactor the logging in all modules in parallel, then tell me which ones failed"
        self.assertFalse(refuses_dag_ulw(message))
        self.assertTrue(self._dag_ulw_starts(message)[0])

    def test_a_missing_skill_catalog_is_not_kept(self) -> None:
        # With no sidecar the catalog names are unknown, and that is not kept: once the sidecar answers, a request
        # that opens with a catalog skill's name is that skill's again.
        from omh.plugin_bundle.omh import dag_ulw_cues

        dag_ulw_cues._CATALOG_SKILL_NAMES.clear()
        try:
            with mock.patch.object(dag_ulw_cues._skill_shortlist, "catalog_skill_names", return_value=None):
                self.assertFalse(dag_ulw_cues._opens_with_a_skill_name("code-review 모든 패키지 버전 올려줘"))
            with mock.patch.object(
                dag_ulw_cues._skill_shortlist, "catalog_skill_names", return_value=frozenset({"code-review"})
            ):
                self.assertTrue(dag_ulw_cues._opens_with_a_skill_name("code-review 모든 패키지 버전 올려줘"))
        finally:
            dag_ulw_cues._CATALOG_SKILL_NAMES.clear()

    def test_no_new_work_over_many_targets_starts_or_offers_nothing(self) -> None:
        # Neither the router nor the hint starts dag-ulw, and no offer names it: a past or a completion, a stop or a
        # hold, a negation or no need, a lookup, a summary or a share, a report, one numbered pull request, a
        # condition, one command over everything, one change in many places, a question, work until a condition, and
        # a request that opens with a skill's name, ulw or a retired engine (#2232 review).
        for message in ("열린 PR들 전부 리베이스했습니다", "PR들 전부 머지했어요", "PR들 전부 머지됐네", "PR들 전부 닫혔네",
                        "브랜치들 다 정리됨", "upstream PR들 다 리뷰 반영 끝", "PR들 전부 확인했어",
                        "열린 PR들 전부 머지 보류해줘", "PR들 전부 리베이스 중단해줘", "모든 서비스 배포 멈춰줘",
                        "모든 서비스 업데이트 취소해줘", "PR들 전부 머지 금지", "PR들 전부 머지하지 마",
                        "PR들 전부 머지하면 안 돼", "PR들 전부 머지할 필요는 없어", "실패하는 테스트 다 안 고쳐도 돼",
                        "upstream PR들 전부 현황 파악해줘", "PR들 전부 요약해줘", "모든 레포 라이선스 조사해줘",
                        "모든 모듈 구조 설명해줘", "각 엔드포인트 응답 시간 측정해줘", "PR들 전부 슬랙에 공유해줘",
                        "PR들 전부 알려줘", "모든 서비스 상태 확인해줘", "check the status of all open PRs",
                        "review all open PRs and send me a list of risky ones", "audit all the repos and send me the findings",
                        "PR들 전부 리뷰하고 결과만 정리해줘", "review all open PRs and just tell me which are safe",
                        "review every file in pull request 2232 and fix what's wrong", "2232번 PR 파일들 전부 리뷰해줘",
                        "내 PR 파일들 전부 리뷰해줘", "review all the files touched by PR 2232", "review all the files in this PR",
                        "fix all the tests in this PR", "fix the login bug on every page", "fix the bug in all three services",
                        "update the copyright year in all files", "테스트 다 통과하면 머지해줘", "PR 다 올렸으면 리뷰 요청해줘",
                        "서비스 다 내려가면 나한테 전화해줘", "패키지 다 설치되면 서버 띄워줘", "전체 서비스 재시작해줘",
                        "모든 브랜치 푸시해줘", "전체 테스트 돌려줘", "모든 파일 포맷팅해줘", "모든 서비스 env 파일 하나로 합쳐줘",
                        "각 파일 첫 줄만 뽑아줘", "README 오타 전부 고쳐줘", "모든 테스트가 깨졌어, 고쳐줘", "PR들 전부 머지됐어?",
                        "are all the tests passing?", "fix all the failing tests until the suite is green",
                        "모든 테스트 통과할 때까지 다 고쳐줘", "team 실패하는 테스트 다 고쳐", "ask 실패하는 테스트 다 고쳐",
                        "ulw 실패하는 테스트 다 고쳐", "울트라워크로 모든 서비스 업데이트해줘", "프로파일 전부 지워줘",
                        "고객서비스 전부 개선해줘", "이 버그 pr 리뷰해줘",
                        # #2232 review: one numbered pull request in more forms, one fault said as "does not work", a
                        # push over everything, a clause before a bare request ending, a report after a review.
                        "update all snapshots in PR number 2240", "github.com/rlaope/oh-my-hermes/pull/2240 의 테스트 전부 고쳐줘",
                        "https://github.com/rlaope/oh-my-hermes/pull/2240 의 테스트 전부 고쳐줘",
                        "fix all the tests in https://github.com/rlaope/oh-my-hermes/pull/2240",
                        "2240번 풀리퀘 모든 테스트 다시 고쳐줘", "2240번 풀 리퀘스트 테스트 전부 고쳐줘",
                        "모든 서비스에서 로그인이 안 돼 고쳐줘", "모든 서비스에서 결제가 안 돼 고쳐줘",
                        "모든 페이지에서 버튼이 안 눌려, 고쳐줘", "모든 페이지에서 모달이 안 떠 고쳐줘", "모든 서비스 로그인 먹통이야 고쳐줘",
                        "모든 브랜치 push 해줘", "PR들 다 리베이스하려고 해", "PR들 전부 리베이스해야 해",
                        "PR들 전부 리베이스 완료됨", "review all open PRs and send me a list of risky ones",
                        # #2232 review 2: a recurring schedule, one PR or branch singled out, one fault in any words,
                        # and no-work twins of the new request forms.
                        "30분마다 열린 PR들 전부 리베이스해줘", "매주 월요일 레포들 전부 의존성 업데이트해줘",
                        "update every service nightly", "아침마다 모든 브랜치 main에 리베이스해줘", "PR 올릴 때마다 테스트 전부 고쳐줘",
                        "방금 올린 PR 파일들 전부 리뷰 반영해줘", "feature/dag-default 브랜치 테스트 전부 고쳐줘",
                        "모든 테스트가 안 돌아가 고쳐줘", "PR들 전부 CI가 안 돌아 고쳐줘", "모든 페이지 다크모드가 안 먹어 고쳐줘",
                        "모든 페이지가 하얗게 나와 고쳐줘", "모든 테스트가 돌지 않아 고쳐줘", "모든 서비스에서 로그인이 안 돼 수정 부탁",
                        "모든 서비스 업데이트 해 놨어", "PR들 몽땅 머지됐어", "모든 패키지 최신화 완료",
                        "for each of my PRs, tell me the status", "for each of my PRs: summarize the changes",
                        "PR들 몽땅 리베이스할까?", "PR 3개 중 하나 리베이스해줘", "PR들 전부 머지하지마", "PR들 전부 고쳐?",
                        "PR들 쭉 리베이스했어"):
            with self.subTest(message=message):
                self.assertFalse(dispatches_dag_ulw(message))
                self.assertFalse(work_over_many_targets(message))
                router, hint, candidate = self._dag_ulw_starts(message)
                self.assertFalse(router)
                self.assertFalse(hint)
                self.assertNotEqual(candidate, "dag-ulw")

    def test_a_question_about_dag_ulw_is_answered_whichever_skill_scored(self) -> None:
        for message in ("dag ulw는 뭐야?", "dag ulw 설명해줘", "how does dag-ulw handle repairs?", "tell me about dag-ulw",
                        "dag ulw 결과 알려줘", "dag ulw 쓰면 비용이 얼마나 나와?", "dag ulw 문서 보여줘", "dag ulw 어떻게 써?",
                        "dag ulw is broken, it never settles the verify node", "can you explain dag ulw?",
                        "can you dag ulw this or should I just fix it myself?", "would you dag ulw it, if you were me?",
                        "can you dag ulw the migration 아니면 그냥 ultrawork로 할까?",
                        # A complaint after the name reports a problem (`name_report_cues`).
                        "dag ulw broke my build", "dag ulw failed again", "dag ulw 너무 느려", "dag ulw 또 실패했어",
                        "dag ulw 때문에 빌드 깨졌어", "ulw dag ordering looks wrong in the docs", "dag ulw 멈춘 듯",
                        "dag ulw spawned too many agents", "dag ulw 결과가 이상해",
                        # So does a question after it, whatever it asks about: dag-ulw only runs work.
                        "dag ulw run finished, now what", "dag ulw 결제 api 뭐야", "dag ulw 결제 취소 api 뭐야",
                        "dag ulw 이거 어떻게 써", "dag ulw how does the verify node work"):
            with self.subTest(message=message):
                self.assertTrue(asks_about_dag_ulw(message))
                route = route_chat_message(message, source="discord")
                self.assertEqual((route["action"], route["selected_skill"]), ("fallback", "oh-my-hermes"))
                self.assertFalse([hint for hint in awareness_route_hint(message)["hints"]
                                  if hint.get("workflow") == "dag-ulw"])
        for message in ("dag ulw는 취소 어떻게 해?", "dag ulw 취소할 수 있어?", "dag ulw 취소 어떻게 해", "dag ulw 취소 방법 알려줘",
                        "dag ulw 취소할 수 있어", "dag ulw 취소 가능해", "dag ulw 취소 뭐야", "dag ulw 취소 왜 했어",
                        "dag ulw 취소해줘 왜 안 돼", "dag ulw 멈출 수 있어", "dag ulw 중단하면 어떻게 돼",
                        # Whether it stopped: a past or passive form, or 여부.
                        "dag ulw 취소됐어?", "dag ulw 멈췄어?", "dag ulw 중단됐나?", "dag ulw 종료됐어?", "dag ulw 취소했어?",
                        "dag ulw 주문 취소됐어?", "dag ulw 취소된 거 맞아?", "dag ulw 취소 완료됐어?", "dag ulw 그만뒀어?",
                        "dag ulw 결과 보고 취소 여부 결정할게",
                        # A status check before a past stop asks whether it stopped; it is no re-run.
                        "dag ulw 확인해줘, 취소됐는지", "dag ulw 보여줘, 취소된 거", "dag ulw 봐줘, 아까 취소한 거 끝났는지",
                        "dag ulw 살펴봐줘, 중단된 거", "dag ulw 체크해줘 아까 멈춘 거", "dag ulw 확인해줘 아까 멈춘 거",
                        "dag ulw 취소 눌렀어?", "dag ulw 멈춘 거 확인해줘", "dag ulw 취소 여부 확인해줘",
                        # A sigil before a question is a question.
                        "/dag-ulw 취소 어떻게 해", "$dag-ulw 취소 방법 알려줘"):
            with self.subTest(message=message):
                # Asking how to cancel, or whether one can, is a question about the skill, not a stop or a run.
                self.assertEqual(dag_ulw_control(message), "")
                self.assertTrue(asks_about_dag_ulw(message))
                self.assertFalse(invokes_dag_ulw(message))
                self.assertEqual(route_chat_message(message, source="discord")["action"], "fallback")
                self.assertFalse(awareness_route_hint(message)["hints"])
        for message in ("/dag-ulw what is it?", "/dag-ulw how do I cancel the run?"):
            with self.subTest(message=message):
                self.assertFalse(invokes_dag_ulw(message))
                route = route_chat_message(message, source="discord")
                self.assertEqual((route["action"], route["selected_skill"]), ("fallback", "oh-my-hermes"))
        self.assertTrue(invokes_dag_ulw("/dag-ulw migrate the billing service"))
        for message in ("/dag-ulw explain the plan, then run the migration",
                        "/dag-ulw is the auth refactor done? if not, finish it",
                        "/dag-ulw what's left of the migration, finish it",
                        "/dag-ulw how do I fix the auth bug? fix it"):
            with self.subTest(message=message):
                # A question that goes on to ask for work is still a command.
                self.assertTrue(invokes_dag_ulw(message))
        self.assertEqual(dag_ulw_control("dag ulw 그만큼 빠르게"), "")  # 그만큼 ("that much") holds no stop word
        self.assertFalse(asks_about_dag_ulw("dag ulw add the export API and its docs"))
        self.assertFalse(asks_about_dag_ulw("can you dag ulw the migration?"))

    def test_a_polite_request_runs_it_on_both_paths(self) -> None:
        for message in ("can you dag ulw the migration?", "could you please dag ulw the billing refactor"):
            with self.subTest(message=message):
                route = route_chat_message(message, source="discord")
                self.assertEqual((route["action"], route["selected_skill"]), ("dispatch", "dag-ulw"))
                hints = awareness_route_hint(message)["hints"]
                self.assertEqual((hints[0]["workflow"], hints[0]["next_action"]), ("dag-ulw", "start_dag_run"))

    def test_small_coding_work_stays_on_ultrawork(self) -> None:
        for message in ("rename the helper function in the parser module", "fix the flaky checkout test",
                        "build a login component"):
            with self.subTest(message=message):
                self.assertEqual(route_chat_message(message)["selected_skill"], "ultrawork")

    def test_inside_hermes_the_route_hint_reaches_dag_ulw_the_same_way(self) -> None:
        # The review's three sentences: big work by intent reaches dag-ulw in Hermes' own per-turn hint too.
        for message in ("implement the export feature in parallel across the api and ui modules, then integrate",
                        "split this into parallel work lanes with disjoint ownership",
                        "do the api and the ui in parallel then integrate"):
            with self.subTest(message=message):
                hints = awareness_route_hint(message)["hints"]
                self.assertEqual((hints[0]["workflow"], hints[0]["next_action"]), ("dag-ulw", "start_dag_run"))
                self.assertEqual(route_chat_message(message, source="discord")["selected_skill"], "dag-ulw")
        for message in ("fix the bug where uploads run in parallel and corrupt the file", "list all modules that import requests",
                        "the fan out of this function is too high, fix it", "동시에 두 요청이 오면 캐시가 깨지는 버그 고쳐줘",
                        "the fan out across the services is too high", "split the paragraph into parallel parts for the translation",
                        "what does it mean to fan out across services", "api 모듈과 ui 모듈이 동시에 요청하면 캐시가 깨져, 고쳐줘"):
            with self.subTest(message=message):
                self.assertFalse([hint for hint in awareness_route_hint(message)["hints"]
                                  if hint.get("workflow") == "dag-ulw"])

    def test_a_stop_or_status_word_for_the_run_starts_nothing_and_points_at_the_run(self) -> None:
        # The delta review's sentences: a person stopping or checking a paid run must not be steered into another.
        cancel = ("dag ulw stop", "dag ulw cancel the run", "dag ulw 멈춰", "dag ulw 그만해", "dag ulw 취소",
                  "dag ulw 중지해줘", "dag ulw 돌린 거 취소해줘", "/dag-ulw stop", "cancel dag ulw",
                  # A verb ending after any words, or a word for the run before the stop noun (owner decision O7).
                  "dag ulw 주문 취소해줘", "dag ulw 주문취소해줘", "dag ulw 작업 취소", "dag ulw 실행 중단", "dag ulw 런 취소",
                  "dag ulw 지금 거 취소", "dag ulw 지금 돌리는 거 취소", "dag ulw의 실행 취소",
                  # Polite and casual verb endings, and 그만 돌려.
                  "dag ulw 취소하세요", "dag ulw 취소해요", "dag ulw 취소할게", "dag ulw 취소합니다", "dag ulw 취소 부탁해",
                  "dag ulw 취소 부탁드려요", "dag ulw 취소 좀 해줘", "dag ulw 취소요", "dag ulw 취소좀", "dag ulw 취소 ㄱ",
                  "dag ulw 주문 취소하세요", "dag ulw 그거 취소해요", "dag ulw 그만 돌려", "dag ulw 멈춰요", "dag ulw 그만하세요",
                  # A modified word for the run, or a stop adverb.
                  "dag ulw 진행 중인 작업 취소", "dag ulw 현재 작업 취소", "dag ulw 이번 실행 취소", "dag ulw 방금 거 취소",
                  "dag ulw 아까 그거 취소", "dag ulw 모든 작업 취소", "dag ulw 전체 취소", "dag ulw 바로 취소", "dag ulw 즉시 중단",
                  "dag ulw 지금 진행 중인 작업 바로 취소해줘", "dag ulw 지금 바로 취소", "dag ulw 그것도 취소",
                  "dag ulw 이전 거 취소", "dag ulw 취소요",
                  # The commonest polite ending and other plain stops, and stop words beyond 취소/중지/중단.
                  "dag ulw 취소해줘요", "dag ulw 중단해줘요", "dag ulw 멈춰줘요", "dag ulw 그만해줘요", "dag ulw 작업 취소해줘요",
                  "dag ulw 주문 취소해줘요", "dag ulw 취소시켜줘요", "dag ulw 취소해줄래요", "dag ulw 그만둬요", "dag ulw 그만 돌리자",
                  "dag ulw 멈춰라", "dag ulw 취소해봐", "dag ulw 취소 ㄱㄱ", "dag ulw 취소하고 싶어", "dag ulw 취소해야 해",
                  "dag ulw 정지해줘", "dag ulw 종료해줘", "dag ulw 스톱", "dag ulw 꺼줘", "dag ulw 취소해줄 수 있어?",
                  "dag ulw 다른 거 취소", "dag ulw 저거 말고 이거 취소", "dag ulw 테스트 실패하면 멈춰",
                  # The act of stopping after the bare stop word or words for the run, and a stop that did not take.
                  "dag ulw 작업 취소 처리해줘", "dag ulw 지금 돌리는 거 취소 처리해줘", "dag ulw 이번 실행 중단 처리해줘",
                  "dag ulw 런 종료 처리해줘", "dag ulw 취소 처리해줘", "dag ulw 작업 취소 진행해줘", "dag ulw 취소 요청해줘",
                  "dag ulw 런 중단 요청 보내줘", "dag ulw 취소 눌러줘", "dag ulw 취소 실행해줘", "dag ulw 중단 명령 내려줘",
                  "dag ulw 취소 처리", "dag ulw 작업 취소 좀 진행해 주세요", "dag ulw 취소 요청",
                  # A halt put on the run, a processed cancel with a softener, and a cancel button pressed while the
                  # run goes on.
                  "dag ulw 작업 중단 걸어줘", "dag ulw 중단 걸어줘", "dag ulw 작업 취소 처리 좀",
                  "dag ulw 취소 버튼 눌렀는데 계속 돌아가",
                  # A stop with its reason after it.
                  "dag ulw stop, too expensive", "dag ulw cancel, wrong task",
                  "dag ulw 취소했는데 계속 돌아가", "dag ulw 취소했는데 아직 안 멈춰", "dag ulw 취소 눌렀는데 계속 돌아가",
                  "dag ulw 멈춤",
                  "dag ulw 취소해 주시겠어요?", "dag ulw 취소해주실래요",
                  # A polite opener or a trailing please before an English stop word.
                  "can you stop dag ulw", "could you cancel the dag ulw run", "can you please cancel dag ulw?",
                  "would you stop the dag ulw run now", "stop dag ulw please")
        status = ("dag ulw status", "dag ulw 상태 보여줘", "dag ulw 진행 상황", "dag ulw 로그 보여줘")
        for message, action in [*((m, "cancel") for m in cancel), *((m, "show_status") for m in status)]:
            with self.subTest(message=message):
                self.assertFalse(invokes_dag_ulw(message))
                self.assertEqual(route_chat_message(message, source="discord")["action"], "fallback")
                payload = awareness_route_hint(message)
                self.assertEqual([(hint["workflow"], hint["next_action"]) for hint in payload["hints"]],
                                 [("dag-ulw", action)])
                context = awareness_route_hint_context_from_payload(payload)
                self.assertIn("call omh_dag action=cancel to stop the run in progress, or action=status", context)
                self.assertNotIn("Start at once", context)
                self.assertNotIn("plan_todo=", context)
        # Work that names a cancel button, a status page or a log-in is still work.
        for message in ("dag ulw add a cancel button to the checkout", "dag ulw build the status page",
                        "dag ulw stop words in the search index", "dag ulw 결제 취소 기능 구현해줘",
                        "dag ulw 상태 관리 모듈 리팩터링해줘", "dag ulw 로그인 기능 구현해줘", "dag ulw 주문 취소 기능 구현해줘",
                        # A work noun or verb after the stop word, or a clause that makes it a condition of the work.
                        "dag ulw 주문 취소 로직 좀 정리해줘요", "dag ulw 결제 취소 플로우 리팩터링 ㄱ",
                        "dag ulw 주문 취소 시 환불되게 해줘", "dag ulw 종료 조건 정리해줘",
                        # 그만큼 ("that much") holds no stop word.
                        "dag ulw 그만큼 빠르게 해줘",
                        # Work words after the stop word, a work-condition clause with nothing else, and an object
                        # before 꺼줘.
                        "dag ulw 결제 취소 이슈 해결해줘", "dag ulw 결제 취소 버그 잡아줘", "dag ulw 결제 취소 디버깅해줘",
                        "dag ulw 결제 취소 쿼리 최적화해줘", "dag ulw 결제 취소 응답 캐싱해줘", "dag ulw 결제 취소 스펙 검토해줘",
                        "dag ulw 주문 취소 문서 써줘", "dag ulw 주문 취소 dto 정의해줘", "dag ulw 중단점 걸고 디버깅해줘",
                        "dag ulw로 중단점 디버깅해줘", "dag ulw 결제 취소 시 쿠폰 복구해줘", "dag ulw 다크모드 꺼줘",
                        "dag ulw 디버그 로그 꺼줘", "dag ulw로 주문 취소 API 만들어줘", "dag ulw 종료 시 정리 작업 추가해줘",
                        # Past the stop word's own ending, a request verb with its own stem: work, whatever the verb.
                        "dag ulw 결제 취소 내역 확인해줘", "dag ulw 결제 취소 내역 롤백해줘", "dag ulw 결제 취소 내역 막아 줘",
                        "dag ulw 결제 취소 내역 재시도하게 해줘", "dag ulw 결제 취소 웹훅 재전송해줘", "dag ulw 종료 훅 등록해줘",
                        "dag ulw 그레이스풀 종료 지원해줘", "dag ulw 배치 중지 스크립트 짜줘", "dag ulw 알림 꺼줘",
                        # A condition clause right before the last stop word, and a past form inside work.
                        "dag ulw 결제 모듈 리팩터링하고 실패하면 중단해줘", "dag ulw 결제 모듈 리팩터링하다가 실패하면 중단",
                        "dag ulw 취소된 주문 정리해줘", "dag ulw 정지된 사용자 목록 api 만들어줘",
                        # A condition after the stop word with no request verb at the end: the condition alone decides.
                        "dag ulw 결제 취소 시 쿠폰 복구", "dag ulw 취소하면 쿠폰 복구",
                        # Work on a cancel, not the act of cancelling the run; and a re-run that names a past stop.
                        "dag ulw 취소 처리 로직 만들어줘", "dag ulw 취소 요청 큐 리팩터링해줘",
                        "dag ulw 다시 돌려줘, 아까 취소한 거", "dag ulw 다시 실행해줘. 어제 중단된 거",
                        "dag ulw 재시작해줘 취소했던 거", "dag ulw 다시 돌려줘 아까 취소한 거", "dag ulw 다시 해줘, 아까 취소한 거 말고",
                        "dag ulw 이어서 해줘 중단된 거", "dag ulw 계속 해줘, 아까 중단된 거", "dag ulw 마저 해줘 중단된 거",
                        "dag ulw 이어서 해줘, 아까 멈춘 거", "dag ulw 마저 해줘, 아까 멈춘 거", "dag ulw 멈춤 버튼 만들어줘",
                        "dag ulw 취소했는데 계속 돌아가는 버그 고쳐줘"):
            with self.subTest(message=message):
                self.assertTrue(invokes_dag_ulw(message))
                self.assertEqual(route_chat_message(message, source="discord")["selected_skill"], "dag-ulw")

    def test_a_stop_noun_after_other_words_asks_whether_to_stop_or_run(self) -> None:
        # Owner decision O7: "주문 취소" names an order cancel as easily as a cancel of the run, so with no verb ending
        # it neither cancels the run nor starts one; both paths ask, naming both readings.
        for message in ("dag ulw 주문 취소", "dag ulw 결제 취소", "dag ulw 예약 취소", "dag ulw 구독 취소",
                        "dag ulw 장바구니 주문 취소", "dag ulw 업로드 중단", "dag ulw 주문취소", "dag ulw 주문을 취소",
                        # Past three words a verb ending asks too: the words may still name the work.
                        "dag ulw 지금 돌리는 결제 모듈 작업 취소해줘", "dag ulw 아까 내가 시작한 결제 작업 좀 취소해줘",
                        # After other words a bare 요, 좀 or ㄱ is no verb; and any other stop with no work after it.
                        "dag ulw 주문 취소요", "dag ulw 결제 취소 좀", "dag ulw 주문 취소 ㄱ",
                        "dag ulw 취소 바람", "dag ulw로 취소해줘", "dag ulw 이 주문 취소", "dag ulw 결과 취소",
                        # The last stop word decides: a stop of the work on a cancel feature asks, never runs.
                        "dag ulw 결제 취소 기능 만드는 거 그만해줘", "dag ulw 주문 취소 로직 작업 중단해줘",
                        "dag ulw 결제 취소 api 작업 멈춰", "dag ulw 주문 취소 기능 구현하던 거 취소해줘",
                        "dag ulw 결제 중단 처리 리팩터링 그만해", "dag ulw 종료 시 정리 작업 하던 거 멈춰줘",
                        "dag ulw 결제 취소 테스트 돌리는 거 중단해", "dag ulw 아까 시작한 주문 취소 기능 작업 취소해줘",
                        "dag ulw 결제 취소 플로우 리팩터링 중단해주세요",
                        "dag ulw 결제 모듈에 주문 취소 기능 넣고 기존 주문 취소해줘",
                        # A stop of the run, then more work: stop and restart, so it asks.
                        "dag ulw 지금 거 취소하고 결제 모듈부터 다시 해줘", "dag ulw 취소하고 다시 처음부터 구현해줘",
                        "dag ulw 취소하고 결과 정리해줘",
                        # 꺼줘 after a word for the run, and a stop left with only its ending past many words.
                        "dag ulw 결제 모듈 작업 꺼줘", "dag ulw 아까 돌린 리팩터링 작업 꺼줘", "dag ulw 테스트 돌리는 거 꺼줘",
                        "dag ulw 결제 작업 취소 좀 빨리 해줘", "dag ulw 아까 그 결제 작업 취소 다시 해줘", "dag ulw 중단하면 돼",
                        # A request before a present stop: it may stop the run in progress, so it still asks.
                        "dag ulw 결제 모듈 리팩터링해줘. 기존 런은 취소",
                        # The stop word's own ending is not a request verb of its own (시켜줘, 둬줘).
                        "dag ulw 아까 내가 시작한 결제 작업 중단시켜줘", "dag ulw 아까 내가 시작한 결제 작업 그만둬줘",
                        # The act of stopping after words that may name the work: processing a cancel, a halt put on
                        # it, a cancel button pressed. The act names no work of its own.
                        "dag ulw 결제 취소 처리해줘", "dag ulw 주문 취소 처리해줘", "dag ulw 결제 취소 진행해줘",
                        "dag ulw 결제 작업 중단 걸어줘", "dag ulw 취소 버튼 눌러줘", "dag ulw 결제 취소 처리 좀",
                        "dag ulw 결제 취소 요청 보내줘",
                        # An English stop word beside words that may name the work.
                        "dag ulw cancel order", "dag ulw order cancel", "dag ulw cancel the migration",
                        "dag ulw stop the billing job"):
            with self.subTest(message=message):
                self.assertEqual(dag_ulw_control(message), "cancel_or_run")
                self.assertFalse(invokes_dag_ulw(message))
                route = route_chat_message(message, source="discord")
                self.assertEqual((route["action"], route["selected_skill"], route["candidate_skill"]),
                                 ("clarify", "oh-my-hermes", "dag-ulw"))
                self.assertIn("stop the dag-ulw run in progress, or start a dag-ulw run", route["clarification"])
                payload = awareness_route_hint(message)
                self.assertEqual([(hint["workflow"], hint["next_action"]) for hint in payload["hints"]],
                                 [("dag-ulw", "ask_one_clarification")])
                self.assertIn("it does neither until the user says which", payload["hints"][0]["reason"])
                context = awareness_route_hint_context_from_payload(payload)
                self.assertIn("Neither define a run nor cancel one yet: ask one short question", context)
                self.assertNotIn("Start at once", context)
                self.assertNotIn("call omh_dag action=cancel to stop the run in progress, or action=status", context)
                self.assertNotIn("plan_todo=", context)

    def test_a_dag_ulw_hint_asks_the_first_response_to_start_at_once(self) -> None:
        # Its lane's card says to plan first and ask; dag-ulw starts at once (owner decision D1), by name or by size.
        for message in ("dag ulw add the export API, its UI button and docs, then verify with the test suite",
                        "split this into parallel work lanes with disjoint ownership"):
            with self.subTest(message=message):
                context = awareness_route_hint_context_from_payload(awareness_route_hint(message))
                self.assertIn("first_response_shape=Start at once: plan the graph and call omh_dag define", context)

    def test_big_parallel_work_reaches_dag_ulw_without_its_name(self) -> None:
        route = route_chat_message("implement the export feature in parallel across the api and ui modules, then integrate")
        self.assertEqual((route["action"], route["selected_skill"]), ("dispatch", "dag-ulw"))


class SigilTests(unittest.TestCase):
    """After the `/dag-ulw` sigil. Hermes sends every `/dag-ulw` turn as one, so these are the turns that run."""

    def _routed(self, message: str) -> tuple[str, str, list[tuple[str, str]]]:
        route = route_chat_message(message, source="discord")
        hints = [(str(hint["workflow"]), str(hint["next_action"])) for hint in awareness_route_hint(message)["hints"]]
        return str(route["action"]), str(route["selected_skill"]), hints

    def test_a_question_after_the_sigil_starts_no_run_in_korean_or_english(self) -> None:
        for message in ("/dag-ulw 이게 뭐야?", "/dag-ulw 이게 뭐야", "/dag-ulw 어떻게 써?", "/dag-ulw dag-ulw가 뭐야?",
                        "/dag-ulw 결제 api 뭐야", "/dag-ulw CI 통과했어?", "/dag-ulw 결제 모듈 리팩터링 끝났어?",
                        "/dag-ulw 이거 병렬로 돌릴 수 있어?", "/dag-ulw what is it?", "/dag-ulw how does it work?",
                        # A question mark that ends it, in any language, as after the bare name.
                        "/dag-ulw did the anti-slop sweep finish?", "/dag-ulw Kubernetes是什么？",
                        # A question after skills stacked on the sigil invokes none of them.
                        "/dag-ulw /ulw-plan what is it?", "/dag-ulw /ulw-plan 이게 뭐야?",
                        # A capability question routes as it does without the sigil, not to dag-ulw's own card.
                        "/dag-ulw 슬랙에서 /omh 치면 뭐가 떠야해?"):
            with self.subTest(message=message):
                action, skill, hints = self._routed(message)
                self.assertFalse(invokes_dag_ulw(message))
                self.assertTrue(asks_about_dag_ulw(message))
                self.assertNotEqual((action, skill), ("dispatch", "dag-ulw"))
                self.assertNotIn(("dag-ulw", "start_dag_run"), hints)
                self.assertFalse([hint for hint in hints if hint[1] in ("present_plan", "start_dag_run")])

    def test_status_and_stop_words_after_the_sigil_point_at_the_run(self) -> None:
        for message, control, hint in (("/dag-ulw 뭐 남았어?", "status", ("dag-ulw", "show_status")),
                                       ("/dag-ulw 상태 보여줘", "status", ("dag-ulw", "show_status")),
                                       ("dag ulw 뭐 남았어?", "status", ("dag-ulw", "show_status")),
                                       ("/dag-ulw what's left?", "status", ("dag-ulw", "show_status")),
                                       ("/dag-ulw 취소해줘", "cancel", ("dag-ulw", "cancel")),
                                       ("/dag-ulw /ulw-plan 취소해줘", "cancel", ("dag-ulw", "cancel")),
                                       ("/dag-ulw 주문 취소", "cancel_or_run", ("dag-ulw", "ask_one_clarification"))):
            with self.subTest(message=message):
                self.assertEqual(dag_ulw_control(message), control)
                action, skill, hints = self._routed(message)
                self.assertNotEqual(action, "dispatch")
                self.assertEqual(hints, [hint])

    def test_a_request_after_the_sigil_still_runs_it(self) -> None:
        for message in ("/dag-ulw 왜 깨졌는지 찾아서 고쳐줘", "/dag-ulw 뭐가 문제인지 보고 PR들 정리해",
                        "/dag-ulw 내가 올린 upstream pr들 전부 확인해서 닫을건 닫고 리뷰반영할건 리뷰반영하고 rebase할건 "
                        "리베이스하고 ㄱㄱ",
                        "/dag-ulw api, ui, docs 작업을 병렬로 나눠서 구현해줄 수 있어?", "/dag-ulw 결제 모듈 고쳐줄래?",
                        "/dag-ulw 나눠서 해주실래요?", "/dag-ulw how do I fix the auth bug? fix it",
                        "/dag-ulw can you dag ulw the migration?", "/dag-ulw migrate the billing service?",
                        "/dag-ulw can we split the api, ui and docs work into parallel lanes?",
                        "/dag-ulw /ulw-plan migrate billing in parts", "/dag-ulw broke the build, fix it"):
            with self.subTest(message=message):
                action, skill, hints = self._routed(message)
                self.assertTrue(invokes_dag_ulw(message))
                self.assertEqual((action, skill), ("dispatch", "dag-ulw"))
                self.assertEqual(hints[0], ("dag-ulw", "start_dag_run"))


if __name__ == "__main__":
    unittest.main()
