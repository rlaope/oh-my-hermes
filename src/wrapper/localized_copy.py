from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChatCopy:
    headline: str
    body: str


def prefers_korean_copy(message: str) -> bool:
    return any("\uac00" <= char <= "\ud7a3" for char in message)


_CARD_COPY: dict[str, dict[str, ChatCopy]] = {
    "img_summary": {
        "en": ChatCopy(
            headline="I can prepare a shareable image card for this.",
            body=(
                "I will turn the source into a shareable image-card brief: audience, layout, on-image copy, "
                "generation prompt, negative prompt, and a quick QA checklist. If no image tool is connected, "
                "I will ask which tool to use instead of pretending an image was generated."
            ),
        ),
        "ko": ChatCopy(
            headline="공유용 이미지 카드 초안을 준비할 수 있습니다.",
            body=(
                "원본 내용을 청중, 레이아웃, 이미지 안 문구, 생성 프롬프트, 네거티브 프롬프트, "
                "간단한 QA 체크리스트로 정리하겠습니다. 연결된 이미지 생성 도구가 없으면 생성했다고 "
                "말하지 않고 어떤 도구를 쓸지 먼저 고릅니다."
            ),
        ),
    },
    "paper_learning": {
        "en": ChatCopy(
            headline="I can explain this paper with the right depth.",
            body=(
                "I will prepare a paper-learning card: explanation level, source/PDF state, section coverage, "
                "key claims, figures or equations to revisit, and a coverage ledger. I will not claim full extraction, "
                "citation checking, math validation, reproduction, or peer review until those are observed."
            ),
        ),
        "ko": ChatCopy(
            headline="논문을 원하는 난이도로 풀어 설명할 수 있습니다.",
            body=(
                "paper-learning 카드로 설명 수준, PDF/출처 상태, 섹션별 커버리지, 핵심 주장, "
                "다시 봐야 할 그림/수식, 누락 범위를 정리하겠습니다. 전문 추출, 인용 검증, "
                "수학 검증, 재현, 피어 리뷰는 관측되기 전까지 완료됐다고 말하지 않습니다."
            ),
        ),
    },
    "source_finder": {
        "en": ChatCopy(
            headline="I can turn this into a source acquisition plan.",
            body=(
                "I will prepare a source-finder plan: typed candidate categories, search/acquisition status, "
                "missing provenance, license or access checks, and the best downstream workflow. I will not claim "
                "web search, download, clone, extraction, verification, or downstream processing until observed."
            ),
        ),
        "ko": ChatCopy(
            headline="자료 탐색을 출처 확보 계획으로 정리할 수 있습니다.",
            body=(
                "source-finder 계획으로 논문, 링크, 데이터셋, 저장소, 발표자료 같은 후보 범주와 "
                "탐색/확보 상태, 출처·라이선스 확인, 다음에 넘길 workflow를 정리하겠습니다. "
                "실제 웹 검색, 다운로드, 클론, 추출, 검증, 후속 처리는 관측되기 전까지 완료됐다고 말하지 않습니다."
            ),
        ),
    },
    "web_research": {
        "en": ChatCopy(
            headline="I can gather source-backed current evidence for this.",
            body=(
                "I will keep this as Hermes-side research: define the source boundaries, freshness window, source diversity, "
                "citation confidence, and retrieval gaps before turning findings into a plan, report, or coding handoff. "
                "I will not claim sources were fetched or verified until observed."
            ),
        ),
        "ko": ChatCopy(
            headline="최신 근거 조사를 Hermes 연구 흐름으로 정리할 수 있습니다.",
            body=(
                "조사 범위, 최신성 기준, 출처 다양성, 인용 신뢰도, 검색 공백을 먼저 잡고 그 다음 "
                "계획, 리포트, 코딩 handoff로 넘기겠습니다. 실제 출처 수집이나 검증은 관측되기 전까지 완료됐다고 말하지 않습니다."
            ),
        ),
    },
    "workflow_learning_missed_route": {
        "en": ChatCopy(
            headline="I can record this missed OMH route.",
            body=(
                "I will treat this as missed-route feedback: record a metadata-only trace, create a reviewable "
                "missed-route bundle, add or request a minimized regression fixture, and keep any routing or skill "
                "change behind human review."
            ),
        ),
        "ko": ChatCopy(
            headline="놓친 OMH 라우팅을 학습 후보로 기록할 수 있습니다.",
            body=(
                "이 요청을 missed-route 피드백으로 다루겠습니다. 원문을 그대로 저장하지 않고 "
                "메타데이터 trace와 리뷰 가능한 bundle을 만들고, 최소 회귀 케이스를 추가하거나 요청합니다. "
                "라우팅/스킬 변경은 사람 리뷰 뒤에만 반영합니다."
            ),
        ),
    },
    "workflow_learning_readiness": {
        "en": ChatCopy(
            headline="I can inspect this workflow for learning readiness.",
            body=(
                "I will turn the workflow attempt into learning material without storing raw prompts: "
                "record the trace, run deterministic evals, add a regression case, audit readiness, "
                "and export a redacted review bundle when useful. Any skill or routing improvement still needs human review."
            ),
        ),
        "ko": ChatCopy(
            headline="이 workflow가 개선 가능한지 점검할 수 있습니다.",
            body=(
                "workflow 실행을 학습 재료로 정리하겠습니다. raw prompt를 저장하지 않고 trace, deterministic eval, "
                "회귀 케이스, readiness audit, redacted review bundle을 만들며, 스킬이나 라우팅 개선은 여전히 사람 리뷰가 필요합니다."
            ),
        ),
    },
    "clarify": {
        "en": ChatCopy(
            headline="I need one clarification before routing this.",
            body="Please confirm the intended workflow before I continue.",
        ),
        "ko": ChatCopy(
            headline="라우팅 전에 한 가지 확인이 필요합니다.",
            body="라우팅 전에 목표를 조금 더 확인해야 합니다. 원하는 결과, 입력 자료, 멈춰야 할 기준을 한 문장으로 알려주세요.",
        ),
    },
    "file_lookup": {
        "en": ChatCopy(
            headline="This looks like a file or text lookup.",
            body="Answer this as a file or text lookup, or ask for the target file/path if it is missing.",
        ),
        "ko": ChatCopy(
            headline="파일이나 텍스트 확인 요청으로 보입니다.",
            body="파일/텍스트 확인으로 바로 답하거나, 대상 파일·경로가 없으면 먼저 물어보세요. OMH workflow 실행은 시작하지 않습니다.",
        ),
    },
    "direct_answer": {
        "en": ChatCopy(
            headline="This does not need an OMH workflow.",
            body="Answer directly in the current chat; do not open an OMH workflow unless the user asks for one.",
        ),
        "ko": ChatCopy(
            headline="이건 OMH workflow 없이 바로 답하면 됩니다.",
            body="현재 채팅에서 바로 답하세요. 사용자가 직접 요청하지 않는 한 OMH workflow, picker, coding handoff를 열지 않습니다.",
        ),
    },
    "generic_clarify": {
        "en": ChatCopy(
            headline="I need to understand the goal before routing this.",
            body="Tell me the outcome you want, and I will choose the right workflow.",
        ),
        "ko": ChatCopy(
            headline="라우팅 전에 목표를 조금 더 알아야 합니다.",
            body="원하는 결과를 한 문장으로 알려주면, 그에 맞는 workflow를 고르겠습니다.",
        ),
    },
}


def chat_copy(copy_id: str, *, korean: bool) -> ChatCopy:
    locale = "ko" if korean else "en"
    return _CARD_COPY[copy_id][locale]


def skill_picker_headline(*, catalog_question: bool, korean: bool) -> str:
    if korean and catalog_question:
        return "OMH workflow 목록입니다."
    if korean:
        return "OMH workflow를 바로 고를 수 있습니다."
    return "Here are the OMH workflows." if catalog_question else "Choose an OMH workflow."


def skill_picker_body(*, catalog_question: bool, korean: bool, family_lines: list[str]) -> str:
    family_heading = "Capability families:" if catalog_question else "Families:"
    if korean and catalog_question:
        return "\n".join(
            [
                "`omh list` 같은 shell 명령 승인을 받지 않아도 됩니다. OMH는 계획, 운영, 자료/이미지, 코딩 위임, loop, 상태 확인 workflow를 Hermes 채팅 안에서 고를 수 있게 해줍니다.",
                "",
                "먼저 이렇게 시작하세요:",
                "- Route for me: 요청을 그대로 보내면 Hermes가 안전한 workflow를 고릅니다.",
                "- Choose workflow: OMH capability family에서 직접 고릅니다.",
                "- Search workflows: 하고 싶은 일이 분명할 때 맞는 skill을 찾습니다.",
                "",
                family_heading,
                *family_lines,
            ]
        )
    if korean:
        return "\n".join(
            [
                "시작 방식을 고르세요. 잘 모르겠으면 Route for me를 고르면 Hermes가 요청에서 가장 안전한 다음 workflow를 고릅니다.",
                "",
                "추천 시작점:",
                "- Route for me: 요청을 붙여 넣고 Hermes가 workflow를 고르게 합니다.",
                "",
                family_heading,
                *family_lines,
            ]
        )
    if catalog_question:
        return "\n".join(
            [
                "You do not need to run a shell command for this. OMH covers planning, ops, deliverables, coding handoffs, loops, and status.",
                "",
                "Start here:",
                "- Route for me: let Hermes choose the safest workflow from your message.",
                "- Choose workflow: pick from the OMH capability families.",
                "- Search workflows: find the exact skill when you already know the job.",
                "",
                family_heading,
                *family_lines,
            ]
        )
    return "\n".join(
        [
            "Pick how to start, or choose Route for me and Hermes will select the safest next step from the request.",
            "",
            "Best default:",
            "- Route for me: paste the request and let Hermes choose the workflow.",
            "",
            family_heading,
            *family_lines,
        ]
    )

