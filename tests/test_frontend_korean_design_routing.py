"""Routing baseline at d0d8653c3 (action / selected / top recommendation).

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

Repairs that name a screen but no visual fault (base verdict; 5dc9fb95b sent each to frontend):
대시보드에 어제 매출 데이터가 안 나와 고쳐줘: clarify / oh-my-hermes / workflow-learning
대시보드 API가 500 에러 나는데 고쳐줘: clarify / oh-my-hermes / build-failure-triage
폰 배터리가 빨리 닳는데 고쳐줘: fallback / oh-my-hermes / oh-my-hermes
폰 번호 인증 로직 고쳐줘: clarify / oh-my-hermes / backend
화면 공유가 안 되는데 고쳐줘: clarify / oh-my-hermes / automation-blueprint
관리자 화면 접속이 안 돼 고쳐줘: clarify / oh-my-hermes / agent-ops-review
회원가입 화면에서 이메일 검증이 안 돼 고쳐줘: clarify / oh-my-hermes / connector-operator
결제 화면에서 결제가 두 번 돼 고쳐줘: fallback / oh-my-hermes / oh-my-hermes
이 page 로딩이 너무 느려 고쳐줘: clarify / oh-my-hermes / browser-operator
폰으로 찍은 사진 색감 고쳐줘: dispatch / voice-operator / voice-operator

Fresh non-visual faults on a screen noun (base verdict, unchanged by the guard):
대시보드 차트 숫자가 실제랑 달라 고쳐줘: clarify / oh-my-hermes / data-analysis
폰에서 앱이 자꾸 강제 종료돼 고쳐줘: fallback / oh-my-hermes / oh-my-hermes
로그인 화면에서 비밀번호 재설정 메일이 안 가 고쳐줘: dispatch / browser-operator / browser-operator
화면 잠금 비밀번호 바꾸는 법 알려줘: clarify / oh-my-hermes / frontend
대시보드 CSV 내보내기가 실패해 고쳐줘: clarify / oh-my-hermes / automation-blueprint
모바일 결제 웹훅이 두 번 호출돼 고쳐줘: clarify / oh-my-hermes / voice-operator
폰 액정이 깨졌는데 수리 어디서 해?: fallback / oh-my-hermes / oh-my-hermes
설정 화면에서 저장 버튼 누르면 서버 에러 나 고쳐줘: clarify / oh-my-hermes / backend
대시보드 정렬 순서가 날짜순이 아니야 고쳐줘: clarify / oh-my-hermes / skill-health
폰 와이파이가 자꾸 끊겨 고쳐줘: fallback / oh-my-hermes / oh-my-hermes
화면 보호기 설정 고쳐줘: clarify / oh-my-hermes / frontend
대시보드 권한이 없는 사람도 다 보여 고쳐줘: clarify / oh-my-hermes / skill-health
the dashboard shows stale numbers after deploy, fix it: clarify / oh-my-hermes / skill-health
the signup page sends two confirmation emails, fix it: clarify / oh-my-hermes / browser-operator
fix the memory leak on the settings screen: dispatch / ultrawork / ultrawork
my phone keeps overheating, how do I fix it: clarify / oh-my-hermes / build-failure-triage
the page returns 404 after login, fix it: clarify / oh-my-hermes / browser-operator
the mobile app crashes on launch, fix it: dispatch / feedback-triage / feedback-triage
fix the dashboard cron job that stopped running: clarify / oh-my-hermes / automation-blueprint
the checkout page charges the wrong tax, fix it: fallback / oh-my-hermes / oh-my-hermes

Fresh visual repairs and redesigns (base verdict; now dispatch / frontend):
대시보드 카드가 서로 겹쳐 보여 고쳐줘: clarify / oh-my-hermes / skill-health
폰에서 버튼 글자가 잘려 고쳐줘: fallback / oh-my-hermes / oh-my-hermes
설정 화면 여백이 너무 좁아 다시 잡아줘: clarify / oh-my-hermes / frontend
the dashboard cards overlap on mobile, fix it: clarify / oh-my-hermes / voice-operator
redesign the settings screen, it looks dated: clarify / oh-my-hermes / accessibility-audit
랜딩 페이지 레이아웃 다시 짜줘: dispatch / frontend / frontend
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


FRESH_POSITIVE = (
    "대시보드 카드가 서로 겹쳐 보여 고쳐줘",
    "폰에서 버튼 글자가 잘려 고쳐줘",
    "설정 화면 여백이 너무 좁아 다시 잡아줘",
    "the dashboard cards overlap on mobile, fix it",
    "redesign the settings screen, it looks dated",
    "랜딩 페이지 레이아웃 다시 짜줘",
)
# Each names a screen and asks for a fix, but the fault is data, auth,
# performance, hardware or a photo: base did not send these to frontend.
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


def route(message):
    return build_chat_interaction_payload(message, source="discord")["route"]


class FrontendKoreanDesignRoutingTests(unittest.TestCase):
    def test_design_and_repair_dispatch(self):
        for message in POSITIVE:
            with self.subTest(message=message):
                result = route(message)
                self.assertEqual((result["action"], result["selected_skill"]), ("dispatch", "frontend"))

    def test_neighbours_do_not_name_frontend(self):
        for message in NEGATIVE:
            with self.subTest(message=message):
                result = route(message)
                self.assertNotEqual(result["selected_skill"], "frontend")
                self.assertNotEqual((result.get("recommendations") or [{}])[0].get("skill"), "frontend")

    def test_greenfield_baseline(self):
        result = route("랜딩 페이지 만들어줘")
        self.assertEqual((result["action"], result["selected_skill"]), ("dispatch", "deep-interview"))

    def test_exclusions_do_not_activate_guard(self):
        for message in NEGATIVE:
            with self.subTest(message=message):
                self.assertFalse(policy.frontend_design_guard_applies(policy.normalized_phrase(message)))


    def test_fresh_visual_repairs_dispatch(self):
        for message in FRESH_POSITIVE:
            with self.subTest(message=message):
                result = route(message)
                self.assertEqual((result["action"], result["selected_skill"]), ("dispatch", "frontend"))

    def test_non_visual_repairs_keep_base_route(self):
        for message, expected in NON_VISUAL_REPAIRS:
            with self.subTest(message=message):
                result = route(message)
                top = (result.get("recommendations") or [{}])[0].get("skill")
                self.assertEqual((result["action"], result["selected_skill"], top), expected)
                self.assertFalse(policy.frontend_design_guard_applies(policy.normalized_phrase(message)))

    def test_fresh_non_visual_faults_do_not_dispatch_frontend(self):
        for message in FRESH_NEGATIVE:
            with self.subTest(message=message):
                self.assertNotEqual(route(message)["selected_skill"], "frontend")
                self.assertFalse(policy.frontend_design_guard_applies(policy.normalized_phrase(message)))

    def test_repair_verb_needs_a_visual_cue(self):
        applies = policy.frontend_design_guard_applies
        self.assertFalse(applies(policy.normalized_phrase("화면 고쳐줘")))
        self.assertFalse(applies(policy.normalized_phrase("fix the dashboard page")))
        self.assertTrue(applies(policy.normalized_phrase("화면이 깨져 고쳐줘")))
        self.assertTrue(applies(policy.normalized_phrase("the page is cut off on mobile, fix it")))


if __name__ == "__main__":
    unittest.main()
