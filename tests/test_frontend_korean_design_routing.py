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


if __name__ == "__main__":
    unittest.main()
