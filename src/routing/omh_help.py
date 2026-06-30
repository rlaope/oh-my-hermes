from __future__ import annotations

from functools import lru_cache


_OMH_MARKERS = ("omh", "oh-my-hermes", "oh my hermes", "오마이헤르메스")


@lru_cache(maxsize=4096)
def is_omh_intro_question(message: str) -> bool:
    text = message.strip().lower()
    if not text:
        return False
    if not any(marker in text for marker in _OMH_MARKERS):
        return False
    if any(
        marker in text
        for marker in (
            "status",
            "doctor",
            "health",
            "install",
            "setup",
            "next",
            "상태",
            "설치",
            "셋업",
            "세팅",
            "다음",
        )
    ):
        return False
    catalog_only_markers = (
        "available",
        "workflow",
        "workflows",
        "skill",
        "skills",
        "workflows available",
        "skills available",
        "commands available",
        "deep-interview",
        "ralplan",
        "ultragoal",
        "loop",
        "ultraprocess",
        "list",
        "menu",
        "picker",
        "명령어",
        "스킬",
        "워크플로",
        "워크플로우",
        "有哪些",
        "可用",
        "使える",
    )
    if any(marker in text for marker in catalog_only_markers):
        return False
    intro_markers = (
        "what is",
        "what are you",
        "how do i use",
        "how should i use",
        "how to use",
        "how does",
        "explain",
        "overview",
        "getting started",
        "mental model",
        "뭐야",
        "무엇이야",
        "어떻게 써",
        "어떻게 사용",
        "사용법",
        "소개",
        "설명",
        "何ですか",
        "使い方",
        "是什么",
        "怎么用",
    )
    return any(marker in text for marker in intro_markers)


@lru_cache(maxsize=4096)
def is_omh_quickstart_question(message: str) -> bool:
    text = message.strip().lower()
    if not text:
        return False
    has_omh_marker = any(marker in text for marker in _OMH_MARKERS)
    install_first_use_context = any(
        marker in text
        for marker in (
            "after setup",
            "after install",
            "first run",
            "first use",
            "install",
            "setup",
            "설치",
            "셋업",
            "세팅",
        )
    ) and any(
        marker in text
        for marker in (
            "what next",
            "what should i do next",
            "what do i do next",
            "first run",
            "first use",
            "confusing",
            "confused",
            "처음",
            "첫 실행",
            "첫 사용",
            "이제 뭐",
            "뭘 해야",
            "뭐 해야",
            "헷갈",
            "모르겠",
        )
    )
    if not has_omh_marker and not install_first_use_context:
        return False
    troubleshooting_markers = (
        "does not show",
        "doesn't show",
        "cannot see",
        "can't see",
        "not found",
        "stale",
        "failed",
        "fails",
        "error",
        "안 보여",
        "안보여",
        "못 봐",
        "못봐",
        "안됨",
        "안 돼",
        "실패",
        "오류",
        "에러",
    )
    if any(marker in text for marker in troubleshooting_markers):
        return False
    quickstart_markers = (
        "quickstart",
        "getting started",
        "first use",
        "what next",
        "what should i do next",
        "what do i do next",
        "next action",
        "after setup",
        "after install",
        "installed correctly",
        "setup next",
        "next step",
        "처음",
        "첫 실행",
        "첫 사용",
        "퀵스타트",
        "다음 액션",
        "다음 단계",
        "이제 뭐",
        "뭘 해야",
        "뭐 해야",
        "헷갈",
        "모르겠",
        "설치됐",
        "설치 되었",
        "설치 완료",
    )
    return any(marker in text for marker in quickstart_markers)


@lru_cache(maxsize=4096)
def is_omh_status_question(message: str) -> bool:
    text = message.strip().lower()
    if not text:
        return False
    if not any(marker in text for marker in _OMH_MARKERS):
        return False
    catalog_markers = (
        "what can",
        "what does",
        "available",
        "workflows",
        "skills",
        "commands",
        "뭐 할",
        "뭘 도와",
        "명령어",
        "스킬",
        "워크플로",
    )
    status_markers = (
        "status",
        "health",
        "상태",
        "정상",
        "확인",
        "헬스",
        "진단",
    )
    if any(marker in text for marker in catalog_markers) and not any(marker in text for marker in status_markers):
        return False
    return any(marker in text for marker in status_markers)
