import unittest

from omh.routing.missed_route import (
    has_missed_omh_workflow_context,
    is_missed_omh_workflow_feedback,
    is_missed_route_feedback,
)


class MissedRouteDetectionTests(unittest.TestCase):
    def test_missed_omh_context_covers_domain_recovery_phrasing(self) -> None:
        cases = (
            "이미지 생성 요청을 했는데 OMH를 안 썼어",
            "회의록 요약을 부탁했는데 OMH 안 쓰고 일반 답변했어",
            "Hermes skipped OMH for my image request",
            "Hermes was not aware of OMH for the research request",
            "디스코드에서 OMH가 자꾸 일반 답변으로 빠져",
            "프리렌이 omh 기능을 모르는 것 같아",
            "agent가 omh context를 못 보는 것 같아",
        )

        for message in cases:
            with self.subTest(message=message):
                self.assertTrue(has_missed_omh_workflow_context(message))

    def test_missed_route_feedback_covers_wrapper_primary_action_phrasing(self) -> None:
        cases = (
            "missed route: OMH was not used",
            "wrong workflow, expected OMH",
            "이번 요청에서 왜 OMH를 안 썼는지 학습해줘",
            "라우팅 누락 기록해줘",
            "라우터가 잘못 고른 것 같아",
            "일반 답변으로 빠져",
        )

        for message in cases:
            with self.subTest(message=message):
                self.assertTrue(is_missed_route_feedback(message))

    def test_missed_omh_workflow_feedback_requires_omh_context(self) -> None:
        self.assertTrue(is_missed_omh_workflow_feedback("프리렌이 OMH 기능을 안 썼어"))
        self.assertFalse(is_missed_omh_workflow_feedback("wrong workflow, expected feedback triage"))


if __name__ == "__main__":
    unittest.main()
