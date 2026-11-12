"""The frontend design guard: whole-request shapes only, everything else keeps its route.

Every expected verdict below is (action, selected skill, top recommendation) as
measured on d0d8653c3, the tree without the guard. The fifteen messages of the
first brief:

대시보드 다시 디자인해줘: clarify / oh-my-hermes / skill-health
이 화면 모바일에서 깨지는데 폰 화면 고쳐줘: clarify / oh-my-hermes / frontend
폰에서 가로 스크롤 생기는데 고쳐줘: clarify / oh-my-hermes / frontend
관리자 화면 레이아웃 다시 잡아줘: dispatch / frontend / frontend
our pages all look the same, make the design less generic: clarify / oh-my-hermes / frontend
랜딩 페이지 다시 디자인해줘: clarify / oh-my-hermes / browser-operator
랜딩 페이지 만들어줘: dispatch / deep-interview / deep-interview
스킬 대시보드 보여줘: dispatch / skill-health / skill-health
대시보드 지표 분석해줘: clarify / oh-my-hermes / skill-health
모바일 앱 스토어 출시 준비해줘: clarify / oh-my-hermes / cto-loop
iOS 앱 화면 디자인 리뷰해줘: clarify / oh-my-hermes / code-review
랜딩 페이지 소개 영상 만들어줘: dispatch / deep-interview / deep-interview
폰 화면 녹화한 영상 편집해줘: clarify / oh-my-hermes / frontend
대시보드가 뭐야?: fallback / oh-my-hermes / oh-my-hermes
디자인 규칙을 빌드에서 검사하게 해줘: clarify / oh-my-hermes / award-bar-score

Two earlier shapes of the guard read cue words anywhere in the message and
dispatched the requests in NON_VISUAL_REPAIRS and OVERREACH_REGRESSIONS to
frontend. Those tuples and RULE_A carry the base verdict beside each sentence.
"""
import unittest

from omh.routing import policy
from omh.wrapper.contract import build_chat_interaction_payload

POSITIVE = (
    "대시보드 다시 디자인해줘",
    "이 화면 모바일에서 깨지는데 폰 화면 고쳐줘",
    "폰에서 가로 스크롤 생기는데 고쳐줘",
    "관리자 화면 레이아웃 다시 잡아줘",
    "our pages all look the same, make the design less generic",
    "랜딩 페이지 다시 디자인해줘",
)
NEGATIVE = (
    "스킬 대시보드 보여줘",
    "대시보드 지표 분석해줘",
    "모바일 앱 스토어 출시 준비해줘",
    "iOS 앱 화면 디자인 리뷰해줘",
    "랜딩 페이지 소개 영상 만들어줘",
    "폰 화면 녹화한 영상 편집해줘",
    "대시보드가 뭐야?",
    "디자인 규칙을 빌드에서 검사하게 해줘",
)
# One request per closed shape, with the tier the predicate names for it.
TIER_EXAMPLES = (
    ("design_intent", "대시보드 다시 디자인해줘"),
    ("design_intent", "우리 홈페이지를 좀 리디자인해 주세요"),
    ("design_intent", "이 화면 다시 디자인해줘"),
    ("design_intent", "please redesign our landing page"),
    ("design_intent", "our screens all look the same, please make the design less generic"),
    ("viewport_scroll_fault", "폰에서 가로 스크롤 생기는데 고쳐줘"),
    ("viewport_scroll_fault", "대시보드에 모바일에서만 가로 스크롤이 생겨서 좀 수정해주세요"),
    ("viewport_scroll_fault", "fix the horizontal scrollbar on phones, please"),
    ("viewport_break_fault", "이 화면 모바일에서 깨지는데 폰 화면 고쳐줘"),
    ("viewport_break_fault", "모바일에서 홈페이지가 깨져서 수정해줘"),
)
# The same words with one thing outside the shape: the guard stands down.
STAND_DOWN = (
    # a qualifier before the surface, or another object after it
    "매출 대시보드 다시 디자인해줘",
    "redesign the dashboard database schema",
    # a question, or a clause after the request
    "대시보드 다시 디자인해줘?",
    "should we redesign the dashboard",
    "대시보드 다시 디자인해줘 그리고 배포해줘",
    # a fault with no viewport, and a scroll with no place
    "화면 깨져 고쳐줘",
    "이 화면 깨지는데 고쳐줘",
    "가로 스크롤 생기는데 고쳐줘",
    # a bare 화면 is also the glass of a phone; a bare page is also a document page
    "화면 다시 디자인해줘",
    "화면이 폰에서 깨져 고쳐줘",
    "이 페이지 다시 디자인해줘",
    "redesign this page",
    # the repair verb alone
    "대시보드 고쳐줘",
    "fix the dashboard",
)
# Overlap, cut off, 겹쳐, 잘려 and 여백 have everyday non-UI readings, and the
# element nouns that would anchor them do too (a payment card, a database
# column), so no shape reads them. These stay where the base puts them.
AMBIGUOUS_SYMPTOMS_LEFT_AT_BASE = (
    "대시보드 테이블 열이 겹쳐 보여 고쳐줘",
    "모바일에서 카드 여백이 너무 좁아 수정해줘",
    "설정 화면 버튼 글자가 잘려 고쳐줘",
    "the pricing page cards overlap on mobile, fix it",
    "대시보드 카드가 서로 겹쳐 보여 고쳐줘",
    "폰에서 버튼 글자가 잘려 고쳐줘",
    "the page is cut off on mobile, fix it",
    "redesign the settings screen, it looks dated",
)
# Text the router masks before scoring (code, a quote, a link, a path) is still
# part of the request, so the shape must hold on the message as sent.
MASKED_REMAINDERS = (
    "대시보드 `schema.sql` 다시 디자인해줘",
    '대시보드 "DB 스키마" 다시 디자인해줘',
    "대시보드 src/db/schema.sql 다시 디자인해줘",
    "redesign the dashboard https://example.com/schema",
    'fix the horizontal scroll on mobile "game levels"',
)
# Each names a screen and asks for a fix, but the fault is data, auth,
# performance, hardware or a photo.
NON_VISUAL_REPAIRS = (
    ("대시보드에 어제 매출 데이터가 안 나와 고쳐줘", ("clarify", "oh-my-hermes", "workflow-learning")),
    ("대시보드 API가 500 에러 나는데 고쳐줘", ("clarify", "oh-my-hermes", "build-failure-triage")),
    ("폰 배터리가 빨리 닳는데 고쳐줘", ("fallback", "oh-my-hermes", "oh-my-hermes")),
    ("폰 번호 인증 로직 고쳐줘", ("clarify", "oh-my-hermes", "backend")),
    ("화면 공유가 안 되는데 고쳐줘", ("clarify", "oh-my-hermes", "automation-blueprint")),
    ("관리자 화면 접속이 안 돼 고쳐줘", ("clarify", "oh-my-hermes", "agent-ops-review")),
    ("회원가입 화면에서 이메일 검증이 안 돼 고쳐줘", ("clarify", "oh-my-hermes", "connector-operator")),
    ("결제 화면에서 결제가 두 번 돼 고쳐줘", ("fallback", "oh-my-hermes", "oh-my-hermes")),
    ("이 page 로딩이 너무 느려 고쳐줘", ("clarify", "oh-my-hermes", "browser-operator")),
    ("폰으로 찍은 사진 색감 고쳐줘", ("dispatch", "voice-operator", "voice-operator")),
)
# The second shape (a surface word with a symptom word) sent all seventeen to
# frontend: each symptom or design word here has its non-UI meaning.
OVERREACH_REGRESSIONS = (
    ("폰 떨어뜨려서 화면 깨져 고쳐줘", ("clarify", "oh-my-hermes", "frontend")),
    ("이 두 위키 page 내용이 겹쳐 하나로 고쳐줘", ("dispatch", "wiki", "wiki")),
    ("these two wiki pages overlap in content, fix by merging them", ("clarify", "oh-my-hermes", "content-operator")),
    ("mobile calls get cut off after 30 seconds, fix the VoIP config", ("clarify", "oh-my-hermes", "parallel-tools")),
    ("the log line for the login screen is cut off, fix the logger", ("clarify", "oh-my-hermes", "accessibility-audit")),
    ("redesign the mobile API authentication flow", ("dispatch", "backend", "backend")),
    ("redesign the dashboard database schema", ("dispatch", "backend", "backend")),
    ("make this wiki page less generic and more specific to our team", ("clarify", "oh-my-hermes", "frontend")),
    ("키보드 레이아웃을 폰에서 한글로 바꿔줘", ("clarify", "oh-my-hermes", "frontend")),
    ("대시보드 쿼리 결과가 잘려 나와 limit 수정해줘", ("clarify", "oh-my-hermes", "skill-health")),
    ("모바일 결제 요청이 겹쳐 들어와 중복 방지 고쳐줘", ("clarify", "oh-my-hermes", "memory-sync")),
    ("화면 캡처 파일명 줄바꿈 문자 들어가는 버그 수정해줘", ("dispatch", "browser-operator", "browser-operator")),
    ("대시보드 CSV 내보내기에서 한글이 깨져 고쳐줘", ("clarify", "oh-my-hermes", "automation-blueprint")),
    ("폰 알림 문자 인코딩이 깨져 나와 고쳐줘", ("dispatch", "gateway-intent-card", "gateway-intent-card")),
    ("page 캐시가 넘쳐 메모리 터져 고쳐줘", ("clarify", "oh-my-hermes", "browser-operator")),
    ("the mobile test suite overlaps with the web suite, fix the CI matrix", ("clarify", "oh-my-hermes", "web-research")),
    ("회의 일정이 화면 공유 시간이랑 겹쳐 수정해줘", ("dispatch", "automation-blueprint", "automation-blueprint")),
)
FRESH_NEGATIVE = (
    "대시보드 차트 숫자가 실제랑 달라 고쳐줘",
    "폰에서 앱이 자꾸 강제 종료돼 고쳐줘",
    "로그인 화면에서 비밀번호 재설정 메일이 안 가 고쳐줘",
    "화면 잠금 비밀번호 바꾸는 법 알려줘",
    "대시보드 CSV 내보내기가 실패해 고쳐줘",
    "모바일 결제 웹훅이 두 번 호출돼 고쳐줘",
    "폰 액정이 깨졌는데 수리 어디서 해?",
    "설정 화면에서 저장 버튼 누르면 서버 에러 나 고쳐줘",
    "대시보드 정렬 순서가 날짜순이 아니야 고쳐줘",
    "폰 와이파이가 자꾸 끊겨 고쳐줘",
    "화면 보호기 설정 고쳐줘",
    "대시보드 권한이 없는 사람도 다 보여 고쳐줘",
    "the dashboard shows stale numbers after deploy, fix it",
    "the signup page sends two confirmation emails, fix it",
    "fix the memory leak on the settings screen",
    "my phone keeps overheating, how do I fix it",
    "the page returns 404 after login, fix it",
    "the mobile app crashes on launch, fix it",
    "fix the dashboard cron job that stopped running",
    "the checkout page charges the wrong tax, fix it",
)
# Rule A: one row per cue in every tuple the predicate reads. The sentence uses
# the cue outside UI work and carries everything else its shape needs (a
# surface and a redesign verb; a viewport, the fault and a repair verb), so
# only the whole-request reading can keep it out. Each keeps its base verdict.
# Base already dispatches the two landing-page rows to frontend on the skill's
# own trigger phrase; the guard adds nothing to them.
RULE_A = (
    ("_FRONTEND_GUARD_DETERMINERS", "이", "이 대시보드 DB 스키마 다시 디자인해줘", ("dispatch", "backend", "backend")),
    ("_FRONTEND_GUARD_DETERMINERS", "우리", "우리 홈페이지 서버 API 다시 디자인해줘", ("dispatch", "backend", "backend")),
    ("_FRONTEND_GUARD_SURFACES", "대시보드", "자동차 대시보드 다시 디자인해줘", ("clarify", "oh-my-hermes", "skill-health")),
    ("_FRONTEND_GUARD_SURFACES", "랜딩 페이지", "랜딩 페이지 전환 실험 다시 디자인해줘", ("clarify", "oh-my-hermes", "browser-operator")),
    ("_FRONTEND_GUARD_SURFACES", "랜딩페이지", "랜딩페이지 로그 스키마 다시 디자인해줘", ("dispatch", "frontend", "frontend")),
    ("_FRONTEND_GUARD_SURFACES", "홈페이지", "홈페이지 백업 정책 다시 디자인해줘", ("fallback", "oh-my-hermes", "oh-my-hermes")),
    ("_FRONTEND_GUARD_POINTED_SURFACES", "이 화면", "이 화면 공유 권한 정책 다시 디자인해줘", ("dispatch", "automation-blueprint", "automation-blueprint")),
    ("_FRONTEND_GUARD_SOFTENERS", "좀", "대시보드 권한 모델 좀 다시 디자인해줘", ("clarify", "oh-my-hermes", "backend")),
    ("_FRONTEND_GUARD_REDESIGN_VERBS", "다시 디자인해", "대시보드 데이터베이스 스키마 다시 디자인해줘", ("clarify", "oh-my-hermes", "backend")),
    ("_FRONTEND_GUARD_REDESIGN_VERBS", "리디자인해", "홈페이지 결제 API 리디자인해줘", ("clarify", "oh-my-hermes", "backend")),
    ("_FRONTEND_GUARD_REQUEST_ENDINGS", "줘", "대시보드 알림 규칙 다시 디자인해줘", ("dispatch", "gateway-intent-card", "gateway-intent-card")),
    ("_FRONTEND_GUARD_REQUEST_ENDINGS", "주세요", "홈페이지 도메인 이전 절차 다시 디자인해주세요", ("dispatch", "live-info-operator", "live-info-operator")),
    ("_FRONTEND_GUARD_VIEWPORTS", "모바일", "모바일에서 엑셀 파일 열면 가로 스크롤 생기는데 고쳐줘", ("dispatch", "materials-package", "materials-package")),
    ("_FRONTEND_GUARD_VIEWPORTS", "폰", "폰에서 PDF 뷰어로 보면 가로 스크롤 생겨서 고쳐줘", ("dispatch", "materials-package", "materials-package")),
    ("_FRONTEND_GUARD_SCROLL_FAULTS", "가로 스크롤", "폰에서 가로 스크롤 슈팅 게임 렉이 생기는데 고쳐줘", ("clarify", "oh-my-hermes", "frontend")),
    ("_FRONTEND_GUARD_APPEAR_FORMS", "생기는데", "폰에서 터미널 로그에 가로 스크롤 생기는데 줄바꿈 옵션 고쳐줘", ("clarify", "oh-my-hermes", "visual-qa")),
    ("_FRONTEND_GUARD_APPEAR_FORMS", "생겨서", "모바일에서 가로 스크롤 로그 수집 누락이 생겨서 수정해줘", ("clarify", "oh-my-hermes", "data-analysis")),
    ("_FRONTEND_GUARD_APPEAR_FORMS", "생겨", "폰에서 가로 스크롤 이벤트 중복 전송이 생겨 고쳐줘", ("clarify", "oh-my-hermes", "frontend")),
    ("_FRONTEND_GUARD_REPAIR_VERBS", "고쳐", "폰에서 가로 스크롤 제스처 통계 누락이 생기는데 집계 쿼리 고쳐줘", ("clarify", "oh-my-hermes", "frontend")),
    ("_FRONTEND_GUARD_REPAIR_VERBS", "수정해", "모바일에서 가로 스크롤 광고 과금 오류가 생겨서 정산 금액 수정해줘", ("clarify", "oh-my-hermes", "frontend")),
    ("_FRONTEND_GUARD_BREAK_FORMS", "깨지는데", "대시보드 CSV 한글이 모바일에서 깨지는데 인코딩 고쳐줘", ("clarify", "oh-my-hermes", "data-analysis")),
    ("_FRONTEND_GUARD_BREAK_FORMS", "깨져서", "홈페이지 첨부 파일명이 폰에서 깨져서 다운로드 로직 수정해줘", ("dispatch", "deliverable-package", "deliverable-package")),
    ("_FRONTEND_GUARD_BREAK_FORMS", "깨져", "홈페이지 백업 압축 파일이 폰에서 깨져 다시 받게 고쳐줘", ("clarify", "oh-my-hermes", "context-budget-review")),
    ("_FRONTEND_GUARD_RESTATED_OBJECTS", "화면", "이 화면 모바일에서 깨지는데 폰 화면 밝기 설정 고쳐줘", ("clarify", "oh-my-hermes", "frontend")),
    ("_FRONTEND_GUARD_EN_POLITE", "please", "please redesign the dashboard database schema", ("dispatch", "backend", "backend")),
    ("_FRONTEND_GUARD_EN_DETERMINERS", "the", "redesign the car dashboard", ("clarify", "oh-my-hermes", "skill-health")),
    ("_FRONTEND_GUARD_EN_DETERMINERS", "our", "redesign our homepage hosting setup", ("clarify", "oh-my-hermes", "buzz")),
    ("_FRONTEND_GUARD_EN_SURFACES", "dashboard", "redesign the dashboard query cache", ("clarify", "oh-my-hermes", "skill-health")),
    ("_FRONTEND_GUARD_EN_SURFACES", "landing page", "redesign the landing page tracking schema", ("dispatch", "frontend", "frontend")),
    ("_FRONTEND_GUARD_EN_SURFACES", "homepage", "redesign the homepage database schema", ("dispatch", "backend", "backend")),
    ("_FRONTEND_GUARD_EN_PLURAL_SURFACES", "pages", "the pages of our pitch deck all look the same, make the design less generic", ("dispatch", "materials-package", "materials-package")),
    ("_FRONTEND_GUARD_EN_PLURAL_SURFACES", "screens", "our recruiter phone screens all look the same, make the design less generic", ("clarify", "oh-my-hermes", "frontend")),
    ("_FRONTEND_GUARD_EN_REDESIGN_VERBS", "redesign", "redesign the homepage caching strategy", ("clarify", "oh-my-hermes", "strategy-brief")),
    ("_FRONTEND_GUARD_EN_SAMENESS", "all look the same", "our pages of unit tests all look the same, make the design less generic", ("clarify", "oh-my-hermes", "frontend")),
    ("_FRONTEND_GUARD_EN_DESIGN_ASKS", "make the design less generic", "our API pages all look the same, make the design less generic in the endpoint naming", ("clarify", "oh-my-hermes", "frontend")),
    ("_FRONTEND_GUARD_EN_REPAIR_VERBS", "fix", "fix the horizontal scroll wheel driver on mobile workstations", ("clarify", "oh-my-hermes", "voice-operator")),
    ("_FRONTEND_GUARD_EN_SCROLL_FAULTS", "horizontal scroll", "fix the horizontal scroll on mobile game levels", ("clarify", "oh-my-hermes", "voice-operator")),
    ("_FRONTEND_GUARD_EN_SCROLL_FAULTS", "horizontal scrollbar", "fix the horizontal scrollbar on phones in the Excel export", ("dispatch", "materials-package", "materials-package")),
    ("_FRONTEND_GUARD_EN_VIEWPORTS", "mobile", "fix the horizontal scroll on mobile mice", ("clarify", "oh-my-hermes", "voice-operator")),
    ("_FRONTEND_GUARD_EN_VIEWPORTS", "phones", "fix the horizontal scroll on phones in our exported spreadsheet", ("clarify", "oh-my-hermes", "materials-package")),
)


def route(message):
    return build_chat_interaction_payload(message, source="discord")["route"]


def verdict(message):
    result = route(message)
    return result["action"], result["selected_skill"], (result.get("recommendations") or [{}])[0].get("skill")


def tier(message):
    return policy.frontend_design_guard_tier(policy.normalized_phrase(message))


class FrontendKoreanDesignRoutingTests(unittest.TestCase):
    def test_design_and_repair_dispatch(self):
        for message in POSITIVE:
            with self.subTest(message=message):
                self.assertEqual(verdict(message), ("dispatch", "frontend", "frontend"))

    def test_neighbours_do_not_name_frontend(self):
        for message in NEGATIVE:
            with self.subTest(message=message):
                _, selected, top = verdict(message)
                self.assertNotEqual(selected, "frontend")
                self.assertNotEqual(top, "frontend")
                self.assertEqual(tier(message), "")

    def test_greenfield_baseline(self):
        self.assertEqual(verdict("랜딩 페이지 만들어줘"), ("dispatch", "deep-interview", "deep-interview"))

    def test_each_shape_names_its_tier_and_dispatches(self):
        for expected, message in TIER_EXAMPLES:
            with self.subTest(message=message):
                self.assertEqual(tier(message), expected)
                self.assertEqual(verdict(message)[:2], ("dispatch", "frontend"))

    def test_one_thing_outside_the_shape_stands_the_guard_down(self):
        for message in STAND_DOWN + AMBIGUOUS_SYMPTOMS_LEFT_AT_BASE:
            with self.subTest(message=message):
                self.assertEqual(tier(message), "")

    def test_masked_text_is_still_part_of_the_request(self):
        for message in MASKED_REMAINDERS:
            with self.subTest(message=message):
                self.assertNotEqual(route(message)["selected_skill"], "frontend")

    def test_guard_has_no_blocker_tuple(self):
        self.assertEqual([name for name in vars(policy) if name.startswith("_FRONTEND") and "BLOCKER" in name], [])

    def test_non_visual_repairs_and_overreach_regressions_keep_base_route(self):
        for message, expected in NON_VISUAL_REPAIRS + OVERREACH_REGRESSIONS:
            with self.subTest(message=message):
                self.assertEqual(verdict(message), expected)
                self.assertEqual(tier(message), "")

    def test_fresh_non_visual_faults_do_not_dispatch_frontend(self):
        for message in FRESH_NEGATIVE:
            with self.subTest(message=message):
                self.assertNotEqual(route(message)["selected_skill"], "frontend")
                self.assertEqual(tier(message), "")

    def test_rule_a_covers_every_cue_the_predicate_reads(self):
        read = {
            (name, cue)
            for name, cues in vars(policy).items()
            if name.startswith("_FRONTEND_GUARD_") and isinstance(cues, tuple) and all(isinstance(cue, str) for cue in cues)
            for cue in cues
        }
        self.assertEqual({(name, cue) for name, cue, _, _ in RULE_A}, read)

    def test_rule_a_sentences_keep_base_route(self):
        for name, cue, message, expected in RULE_A:
            with self.subTest(cue=cue, message=message):
                self.assertIn(cue, getattr(policy, name))
                self.assertIn(policy.normalized_phrase(cue), policy.normalized_phrase(message))
                self.assertEqual(tier(message), "")
                self.assertEqual(verdict(message), expected)


if __name__ == "__main__":
    unittest.main()
