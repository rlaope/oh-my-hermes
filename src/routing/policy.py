from __future__ import annotations

from dataclasses import dataclass

from .intent import classify_omh_quality_intent
from .localization import normalized_phrase, routing_tokens


ROUTE_ACTIONS = ("dispatch", "clarify", "fallback")
CONFIDENCE_LEVELS = ("low", "medium", "high")
EXPLICIT_INVOCATION_PREFIXES = ("$", "/", "./", "@")
_EXPLICIT_SKILL_ALIASES = {
    "ohmy": "oh-my-hermes",
    "paper-explainer": "paper-learning",
    "source-acquisition": "source-finder",
    "source-intake": "source-finder",
}
_PREFIXED_SKILL_ALIASES = {
    "omh": "oh-my-hermes",
    "ohmy": "oh-my-hermes",
    "skills": "oh-my-hermes",
    "paper-explainer": "paper-learning",
    "source-acquisition": "source-finder",
    "source-intake": "source-finder",
}

_CONFIDENCE_RANK = {name: index for index, name in enumerate(CONFIDENCE_LEVELS, start=1)}


def _normalized_token_set(values: set[str]) -> frozenset[str]:
    tokens: set[str] = set()
    for value in values:
        normalized = normalized_phrase(value)
        if normalized:
            tokens.add(normalized)
        tokens.update(routing_tokens(value, stopwords=set()))
    return frozenset(tokens)


_SCHEDULED_OPS_STRONG_TOKENS = _normalized_token_set(
    {
        "cron",
        "recurring",
        "repeat",
        "정기",
        "반복",
    }
)
_SCHEDULED_OPS_CADENCE_TOKENS = _normalized_token_set(
    {
        "daily",
        "weekly",
        "monthly",
        "매일",
        "매주",
        "매월",
    }
)
_SCHEDULED_OPS_CONTEXT_TOKENS = _normalized_token_set(
    {
        "check",
        "checks",
        "monitor",
        "monitoring",
        "watch",
        "watchdog",
        "digest",
        "report",
        "reports",
        "notify",
        "notification",
        "deliver",
        "delivery",
        "slack",
        "discord",
        "telegram",
        "email",
        "competitor",
        "news",
        "source",
        "sources",
        "changed",
        "changes",
        "silent",
        "silently",
        "헬스체크",
        "감시",
        "확인",
        "보고",
        "리포트",
        "요약",
        "알림",
        "슬랙",
        "디스코드",
        "텔레그램",
        "이메일",
        "경쟁사",
        "뉴스",
        "변화",
        "조용히",
    }
)
_RESEARCH_DEPARTMENT_STRONG_TOKENS = _normalized_token_set(
    {
        "research",
        "competitor",
        "competitors",
        "market",
        "industry",
        "paper",
        "papers",
        "notebooklm",
        "obsidian",
        "vault",
        "리서치",
        "조사",
        "경쟁사",
        "시장",
        "산업",
        "논문",
        "옵시디언",
    }
)
_RESEARCH_DEPARTMENT_SUPPORT_TOKENS = _normalized_token_set(
    {
        "news",
        "source",
        "sources",
        "brief",
        "briefing",
        "digest",
        "뉴스",
        "출처",
        "자료",
        "브리핑",
        "요약",
    }
)
_RESEARCH_DEPARTMENT_PHRASES = (
    "research department",
    "research ops",
    "research operations",
    "scout analyst briefer",
    "daily research",
    "weekly research",
    "competitor research",
    "market research",
    "source inbox",
    "briefing status",
    "notebooklm",
    "obsidian vault",
    "리서치 부서",
    "리서치 운영",
    "경쟁사 리서치",
    "시장 리서치",
    "수집 합성 브리핑",
)
_PAPER_LEARNING_PAPER_TOKENS = _normalized_token_set(
    {
        "paper",
        "papers",
        "arxiv",
        "doi",
        "pdf",
        "research paper",
        "논문",
        "피디에프",
    }
)
_PAPER_LEARNING_EXPLANATION_TOKENS = _normalized_token_set(
    {
        "explain",
        "explainer",
        "explanation",
        "summarize",
        "summaries",
        "summary",
        "walkthrough",
        "learn",
        "learning",
        "easy",
        "moderate",
        "expert",
        "technical",
        "details",
        "설명",
        "해설",
        "쉽게",
        "난이도",
        "전문가급",
        "내용",
        "줄이지",
        "요약",
        "resumen",
        "resumir",
        "explicar",
        "説明",
        "要約",
        "解释",
        "解釋",
        "总结",
        "總結",
    }
)
_PAPER_LEARNING_PHRASES = (
    "paper-learning",
    "paper learning",
    "paper-explainer",
    "paper explainer",
    "paper explanation",
    "paper summary",
    "paper summaries",
    "summarize this paper",
    "summarize the attached paper",
    "explain this paper",
    "explain this arxiv paper",
    "explain the attached paper",
    "resumen de paper",
    "resumen de paper pdf",
    "resumen de artículo",
    "resumen de articulo",
    "resumir paper",
    "explicar paper",
    "paper walkthrough",
    "research paper explanation",
    "research paper summary",
    "arxiv paper explain",
    "pdf paper explain",
    "pdf paper summary",
    "paper pdf explanation",
    "paper pdf summary",
    "without dropping details",
    "very easy paper explanation",
    "moderate paper explanation",
    "expert paper explanation",
    "논문 설명",
    "논문 해설",
    "논문 요약",
    "논문 쉽게 설명",
    "논문 아주 쉽게",
    "논문 적당한 난이도",
    "논문 전문가급",
    "이 논문 설명해줘",
    "이 논문 요약해줘",
    "이 논문 pdf 설명해줘",
    "이 논문 pdf 요약해줘",
    "논문 pdf 쉽게 설명",
    "논문 pdf 요약",
    "논문 내용 줄이지 말고",
    "論文pdfを説明",
    "論文pdfを要約",
    "論文を説明",
    "論文を要約",
    "解释论文pdf",
    "解釋論文pdf",
    "总结论文pdf",
    "總結論文pdf",
    "解释这篇论文",
    "解釋這篇論文",
)
_PAPER_LEARNING_EXPORT_PHRASES = (
    "pdf to ppt",
    "pdf into ppt",
    "convert pdf",
    "export pdf",
    "export a pdf",
    "make a pdf",
    "make ppt",
    "make a ppt",
    "make a deck",
    "create a ppt",
    "create a deck",
    "as a deck",
    "as a pdf",
    "package it as a pdf",
    "turn into ppt",
    "turn into a deck",
    "render qa",
    "pdf를 ppt",
    "pdf를 ppt로",
    "pdf로 만들",
    "ppt로 만들",
    "파일 생성",
    "파일 변환",
)
_PAPER_LEARNING_VALIDATION_PHRASES = (
    "verify citations",
    "validate citations",
    "citation check",
    "external citation check",
    "check the citations",
    "verify the claims",
    "validate the claims",
    "fact check",
    "fact-check",
    "proof review",
    "math proof review",
    "reproduce the benchmark",
    "인용 확인",
    "인용 검증",
    "주장 검증",
    "팩트체크",
    "증명 검토",
    "재현해",
)
_SOURCE_FINDER_ACTION_TOKENS = _normalized_token_set(
    {
        "find",
        "discover",
        "collect",
        "gather",
        "candidate",
        "candidates",
        "intake",
        "acquisition",
        "download",
        "downloadable",
        "lookup",
        "찾아",
        "찾아줘",
        "후보",
        "수집",
        "자료",
        "출처",
    }
)
_SOURCE_FINDER_KIND_TOKENS = _normalized_token_set(
    {
        "paper",
        "papers",
        "arxiv",
        "doi",
        "dataset",
        "datasets",
        "benchmark",
        "github",
        "repo",
        "repos",
        "repository",
        "repositories",
        "oss",
        "open-source",
        "presentation",
        "presentations",
        "slides",
        "deck",
        "docs",
        "documentation",
        "spec",
        "specs",
        "rfc",
        "links",
        "논문",
        "데이터셋",
        "데이터",
        "깃허브",
        "저장소",
        "오픈소스",
        "발표자료",
        "슬라이드",
        "문서",
        "스펙",
        "링크",
    }
)
_SOURCE_FINDER_PHRASES = (
    "source-finder",
    "source finder",
    "source acquisition",
    "source intake",
    "source candidates",
    "find source candidates",
    "find papers and datasets",
    "find datasets and repos",
    "find papers",
    "find datasets",
    "find github repos",
    "find github repositories",
    "find oss repos",
    "find open source repos",
    "find presentations",
    "find public slides",
    "find docs and specs",
    "downloadable sources",
    "자료 후보",
    "출처 후보",
    "논문 데이터셋 찾아",
    "논문과 데이터셋",
    "깃허브 저장소 찾아",
    "오픈소스 저장소 찾아",
    "공개 발표자료 찾아",
    "문서 스펙 찾아",
)
_SOURCE_FINDER_EXCLUSION_PHRASES = (
    "find current citations",
    "current citations",
    "citation check",
    "verify citations",
    "source backed synthesis",
    "source-backed synthesis",
    "summarize what the sources say",
    "official docs",
    "official documentation",
    "official guide",
    "official guidance",
    "upstream guidance",
    "best practice",
    "best practices",
    "best practice docs",
    "current api",
    "current version",
    "latest version",
    "fact check",
    "fact-check",
    "latest news",
    "current evidence",
)
_VISUAL_SUMMARY_MODALITY_TOKENS = _normalized_token_set(
    {
        "visual",
        "image",
        "vertical",
        "infographic",
        "poster",
        "one-pager",
        "onepager",
        "graphic",
        "이미지",
        "세로",
        "인포그래픽",
        "포스터",
        "画像",
        "ビジュアル",
        "海报",
        "海報",
        "图",
        "图像",
        "圖片",
        "图片",
    }
) - {"one", "pager"}
_VISUAL_SUMMARY_CARD_TOKENS = _normalized_token_set(
    {"card", "poster", "one-pager", "카드", "포스터", "海报", "海報"}
) - {"one", "pager"}
_VISUAL_SUMMARY_CAPABILITY_TOKENS = _normalized_token_set(
    {
        "support",
        "supports",
        "feature",
        "features",
        "generation",
        "capability",
        "capabilities",
        "available",
        "help",
        "does",
        "can",
        "기능",
        "지원",
        "가능",
        "있어",
        "있나요",
        "できる",
        "支持",
        "功能",
    }
)
_VISUAL_SUMMARY_SHORT_REQUEST_PHRASES = frozenset(
    normalized_phrase(phrase)
    for phrase in (
        "make an image",
        "create an image",
        "generate an image",
        "이미지 만들어줘",
        "이미지 생성해줘",
        "이미지 생성해 줘",
        "이미지를 만들어줘",
        "이미지를 생성해줘",
    )
)
_VISUAL_SUMMARY_NON_VISUAL_WORK_TOKENS = _normalized_token_set(
    {
        "classifier",
        "component",
        "debug",
        "fix",
        "failure",
        "failures",
        "bug",
        "error",
        "errors",
        "upload",
        "uploads",
        "asset",
        "assets",
        "processing",
        "파이썬",
        "python",
        "script",
        "스크립트",
        "스크립트로",
        "컴포넌트",
    }
)
_VISUAL_SUMMARY_OUTPUT_CONTEXT_TOKENS = _normalized_token_set(
    {
        "summary",
        "announcement",
        "briefing",
        "triage",
        "review",
        "release",
        "meeting",
        "notes",
        "pr",
        "pull",
        "request",
        "explain",
        "explainer",
        "explanation",
        "feature",
        "workflow",
        "cron",
        "automation",
        "shareable",
        "research",
        "news",
        "competitor",
        "요약",
        "설명",
        "소개",
        "기능",
        "안내",
        "공유용",
        "워크플로우",
        "브리핑",
        "발표",
        "트리아지",
        "회의",
        "회의록",
        "리서치",
        "뉴스",
        "경쟁사",
        "作成",
        "要約",
        "概要",
        "説明",
        "发布",
        "發布",
        "说明",
        "說明",
        "摘要",
        "总结",
    }
)
_VISUAL_SUMMARY_PHRASES = (
    "img-summary",
    "img summary",
    "visual-summary",
    "visual summary",
    "visual prompt card",
    "image card",
    "image summary card",
    "summary image",
    "summary card",
    "explainer image",
    "feature explainer image",
    "feature explanation image",
    "product explainer image",
    "product explainer card",
    "infographic",
    "one-page infographic",
    "one-page visual",
    "visual one-pager",
    "poster explaining",
    "explainer poster",
    "summary poster",
    "release poster",
    "shareable poster",
    "pr poster",
    "pull request poster",
    "workflow image",
    "workflow card",
    "workflow poster",
    "shareable image",
    "shareable card",
    "shareable visual",
    "explain this as an image",
    "make an image explaining",
    "image explaining the cron feature",
    "make an image explaining the cron feature",
    "make a visual summary of this pr",
    "visual summary of this pr",
    "picture card",
    "meeting notes picture card",
    "pr reviewer image card",
    "make a poster explaining",
    "vertical card",
    "vertical summary image",
    "vertical image card",
    "pr summary card",
    "pull request card",
    "issue triage card",
    "bug triage card",
    "news briefing card",
    "competitor news briefing card",
    "release announcement image",
    "release notes image",
    "회의록을 세로 요약 이미지",
    "회의록 세로 요약 이미지",
    "회의록을 공유용 카드",
    "회의록 공유용 카드",
    "pr 요약 카드",
    "pr 요약 포스터",
    "이슈 트리아지 카드",
    "경쟁사 뉴스 브리핑 카드",
    "릴리즈 노트 발표 이미지",
    "릴리즈 노트 포스터",
    "세로 이미지 카드",
    "세로 이미지로 요약",
    "세로 이미지로 요약해줘",
    "이미지 카드",
    "이미지로 요약",
    "이미지로 요약해줘",
    "회의록 이미지 카드",
    "회의록을 세로 이미지 카드",
    "회의록을 보기 좋은 세로 이미지로 요약",
    "회의록을 보기 좋은 세로 이미지로 요약해줘",
    "설명 이미지",
    "설명하는 인포그래픽",
    "기능 설명 이미지",
    "기능 소개 이미지",
    "크론 기능 설명 이미지",
    "크론 기능 설명 이미지 하나 만들어줘",
    "인포그래픽",
    "인포그래픽 만들어줘",
    "이미지 요약 카드",
    "요약 이미지",
    "요약 카드",
    "카드 이미지",
    "공유용 이미지",
    "안내 이미지",
    "워크플로우 이미지",
    "이미지로 설명",
    "이미지 하나 만들어줘",
    "pr 내용을 리뷰어에게 공유할 이미지 카드",
    "pr 내용을 리뷰어에게 공유할 이미지 카드로 만들어줘",
    "사진 카드",
    "요약 포스터",
    "공유용 카드",
    "공유용 포스터",
    "prの要約画像",
    "要約画像",
    "概要画像",
    "説明画像",
    "发布说明海报",
    "發布說明海報",
    "发布说明图",
    "發布說明圖",
    "总结海报",
    "摘要海报",
)
_OMH_MISSED_WORKFLOW_PHRASES = (
    "did not use omh",
    "didn't use omh",
    "didnt use omh",
    "not using omh",
    "without omh",
    "missed omh",
    "skipped omh",
    "forgot omh",
    "not aware of omh",
    "did not know omh",
    "didn't know omh",
)
_MISSED_WORKFLOW_ACTION_PHRASES = (
    "did not use",
    "didn't use",
    "didnt use",
    "does not use",
    "doesn't use",
    "doesnt use",
    "not using",
    "missed",
    "skipped",
    "forgot",
    "not aware",
    "did not know",
    "didn't know",
    "does not know",
    "몰랐",
    "모르",
    "안 썼",
    "안 써",
    "안쓰",
    "안 쓰",
    "놓쳤",
    "빠졌",
)
_MISSED_WORKFLOW_RESEARCH_TOKENS = _normalized_token_set(
    {
        "research",
        "researching",
        "source",
        "sources",
        "web",
        "search",
        "리서치",
        "조사",
        "자료",
        "출처",
        "웹서치",
        "검색",
    }
)
_MISSED_WORKFLOW_OPERATING_RECORD_TOKENS = _normalized_token_set(
    {
        "meeting",
        "minutes",
        "notes",
        "summary",
        "summarize",
        "decision",
        "decisions",
        "action",
        "actions",
        "회의",
        "회의록",
        "요약",
        "정리",
        "결정",
        "액션",
        "기록",
    }
)
_PRODUCT_SHAPING_PHRASES = (
    "where to start",
    "do not know where to start",
    "don't know where to start",
    "dont know where to start",
    "not sure where to start",
    "improve our onboarding",
    "improve onboarding",
    "make onboarding smoother",
    "make onboarding feel smoother",
    "make the user experience smoother",
    "make the product experience better",
    "온보딩을 더 부드럽게",
    "온보딩 개선",
    "어디서 시작",
    "어디부터 시작",
)
_PRODUCT_SHAPING_CONTEXT_TOKENS = _normalized_token_set(
    {
        "onboarding",
        "activation",
        "conversion",
        "funnel",
        "ux",
        "product",
        "feature",
        "experience",
        "customer",
        "user",
        "users",
        "온보딩",
        "제품",
        "기능",
        "사용자",
        "고객",
        "경험",
    }
)
_PRODUCT_SHAPING_UNCERTAINTY_TOKENS = _normalized_token_set(
    {
        "improve",
        "improvement",
        "better",
        "smoother",
        "smooth",
        "start",
        "where",
        "unclear",
        "vague",
        "fuzzy",
        "unknown",
        "개선",
        "부드럽게",
        "어디",
        "시작",
        "모호",
    }
)
_FEEDBACK_TRIAGE_PHRASES = (
    "customer feedback",
    "customer notes",
    "customer reports",
    "customers report",
    "customers say",
    "user feedback",
    "user reports",
    "users report",
    "users say",
    "app keeps crashing",
    "keeps crashing after login",
    "checkout is broken",
    "checkout keeps failing",
    "payment failures keep coming up",
    "payment failure keeps coming up",
    "what to build next from customer notes",
    "decide what to build next from customer notes",
    "decide what to build next from these customer notes",
    "고객 피드백",
    "고객 노트",
    "고객 제보",
    "사용자 제보",
    "사용자 피드백",
    "결제 실패 이슈",
    "결제 실패가 자주",
    "체크아웃이 깨",
    "체크아웃 실패",
    "로그인 후 크래시",
)
_FEEDBACK_TRIAGE_SOURCE_TOKENS = _normalized_token_set(
    {
        "customer",
        "customers",
        "user",
        "users",
        "feedback",
        "notes",
        "report",
        "reports",
        "reported",
        "signal",
        "signals",
        "고객",
        "사용자",
        "피드백",
        "제보",
        "노트",
        "신호",
    }
)
_FEEDBACK_TRIAGE_PRODUCT_TOKENS = _normalized_token_set(
    {
        "app",
        "product",
        "checkout",
        "payment",
        "billing",
        "login",
        "signup",
        "onboarding",
        "cart",
        "subscription",
        "앱",
        "제품",
        "체크아웃",
        "결제",
        "청구",
        "로그인",
        "가입",
        "온보딩",
    }
)
_FEEDBACK_TRIAGE_ISSUE_TOKENS = _normalized_token_set(
    {
        "bug",
        "bugs",
        "issue",
        "issues",
        "broken",
        "breaks",
        "crash",
        "crashes",
        "crashing",
        "fail",
        "fails",
        "failed",
        "failing",
        "failure",
        "failures",
        "error",
        "errors",
        "problem",
        "problems",
        "버그",
        "이슈",
        "깨",
        "고장",
        "크래시",
        "실패",
        "에러",
        "문제",
    }
)
_FEEDBACK_TRIAGE_DECISION_TOKENS = _normalized_token_set(
    {
        "decide",
        "choose",
        "prioritize",
        "rank",
        "build",
        "next",
        "roadmap",
        "investigate",
        "reproduce",
        "triage",
        "결정",
        "선택",
        "우선순위",
        "다음",
        "로드맵",
        "조사",
        "재현",
        "트리아지",
    }
)
_WORKFLOW_LEARNING_PHRASES = (
    "learn from this workflow",
    "learn from this workflow run",
    "learn from this run",
    "record this as workflow learning",
    "record this workflow learning",
    "record this as a workflow learning trace",
    "record this workflow learning trace",
    "improve the skill next time",
    "improve this skill next time",
    "improve routing next time",
    "make a regression case",
    "add a regression case",
    "why did this route",
    "missed route",
    "missed workflow",
    "record why this request",
    "future workflow behavior",
    "workflow should learn",
    "workflow went wrong",
    "workflow that went wrong",
    "workflow failed",
    "weak workflow",
    "route went wrong",
    "routing went wrong",
    "routing failed",
    "hermes should learn",
    "이번 실행 학습",
    "이번 워크플로우 학습",
    "다음에 스킬 개선",
    "라우팅 회귀",
    "회귀 케이스",
    "omh 안 썼어",
    "omh 안 썼",
    "워크플로 누락",
    "라우팅 누락",
)
_WORKFLOW_LEARNING_ACTION_TOKENS = _normalized_token_set(
    {
        "add",
        "audit",
        "case",
        "candidate",
        "eval",
        "evaluate",
        "export",
        "fix",
        "future",
        "improve",
        "improvement",
        "missed",
        "missing",
        "next",
        "propose",
        "record",
        "recorded",
        "regression",
        "replay",
        "review",
        "trace",
        "why",
        "개선",
        "기록",
        "누락",
        "리뷰",
        "왜",
        "회귀",
    }
)
_WORKFLOW_LEARNING_CONTEXT_TOKENS = _normalized_token_set(
    {
        "learn",
        "learning",
        "workflow",
        "run",
        "trace",
        "skill",
        "routing",
        "route",
        "regression",
        "eval",
        "audit",
        "improve",
        "improvement",
        "candidate",
        "next",
        "future",
        "missed",
        "missing",
        "학습",
        "스킬",
        "워크플로우",
        "라우팅",
        "회귀",
        "개선",
        "실행",
        "누락",
    }
)
_EXECUTOR_RUNTIME_READINESS_PHRASES = (
    "executor-runtime-readiness",
    "runtime readiness",
    "codex readiness",
    "claude code readiness",
    "can this task run in codex",
    "can this run in codex",
    "can this run in claude",
    "run in codex or claude",
    "run in codex, claude",
    "codex or claude",
    "codex and claude",
    "codex vs claude",
    "codex랑 claude",
    "codex랑 claude code",
    "codex와 claude",
    "codex와 claude code",
    "claude code 중",
    "claude code로 넘길지 codex",
    "codex로 넘길지 claude",
    "런타임으로 넘겨",
    "어떤 런타임",
    "넘길지 codex",
    "넘길지 claude",
    "코덱스랑 클로드",
    "코덱스와 클로드",
    "코덱스 클로드",
)
_EXECUTOR_RUNTIME_READINESS_TOKENS = _normalized_token_set(
    {
        "codex",
        "claude",
        "runtime",
        "executor",
        "handoff",
        "agent",
        "omx",
        "omo",
        "omc",
        "런타임",
        "실행",
        "위임",
        "넘길",
        "넘길지",
        "정해",
        "코덱스",
        "클로드",
    }
)
_MATERIALS_PACKAGE_PHRASES = (
    "ppt and pdf",
    "pdf and ppt",
    "ppt/pdf",
    "pdf/ppt",
    "spreadsheet to pdf",
    "excel to pdf",
    "monthly report pdf",
    "attached spreadsheet",
    "첨부한 엑셀",
    "엑셀을 월간 보고서",
    "pdf랑 ppt",
    "ppt랑 pdf",
    "ppt와 pdf",
    "pdf와 ppt",
    "pdf랑 ppt로",
    "make a ppt",
    "make a deck",
    "create a ppt",
    "create a deck",
    "as a deck",
    "export a pdf",
    "export pdf",
    "as a pdf",
    "package it as a pdf",
    "ppt로 만들",
    "pdf로 만들",
)
_MATERIALS_PACKAGE_FORMAT_TOKENS = _normalized_token_set(
    {
        "pdf",
        "ppt",
        "pptx",
        "spreadsheet",
        "excel",
        "xlsx",
        "docx",
        "hwp",
        "document",
        "피디에프",
        "엑셀",
        "문서",
        "자료",
        "첨부",
    }
)
_MATERIALS_PACKAGE_ACTION_TOKENS = _normalized_token_set(
    {
        "make",
        "create",
        "turn",
        "prepare",
        "package",
        "export",
        "share",
        "render",
        "만들",
        "정리",
        "공유",
        "준비",
        "생성",
        "변환",
    }
)
_MEMORY_CURATION_PHRASES = (
    "memory curation",
    "memory review",
    "memory inspect",
    "context cleanup",
    "context compaction",
    "cross-channel context",
    "channel context collision",
    "stale project context",
    "old project context",
    "hermes remembers",
    "기억하고 있는",
    "기억하고 있는 프로젝트 맥락",
    "프로젝트 맥락이 오래된",
    "오래된 맥락",
    "오래된 기억",
    "맥락이 오래된",
    "메모리 압축",
    "채널 용어",
    "용어가 겹",
    "다른 채널",
)
_MEMORY_CURATION_CONTEXT_TOKENS = _normalized_token_set(
    {
        "memory",
        "context",
        "remember",
        "remembers",
        "stale",
        "old",
        "duplicate",
        "cleanup",
        "curate",
        "기억",
        "맥락",
        "메모리",
        "오래된",
        "중복",
        "채널",
        "용어",
        "압축",
        "충돌",
        "정리",
    }
)
_AGENT_BOARD_PHRASES = (
    "agent board",
    "multi agent board",
    "multiple hermes agents",
    "multiple hermes profiles",
    "coordinate pm cto qa",
    "coordinate pm cto qa and release agents",
    "coordinate release agents",
    "roles and board",
    "role board",
    "task board",
    "kanban board",
    "hermes agent 여러 명",
    "여러 명이 같이 일",
    "역할과 보드",
    "역할 보드",
    "작업 보드",
)
_AGENT_BOARD_CONTEXT_TOKENS = _normalized_token_set(
    {
        "agent",
        "agents",
        "profile",
        "profiles",
        "multi",
        "multiple",
        "board",
        "kanban",
        "role",
        "roles",
        "team",
        "hermes",
        "에이전트",
        "여러",
        "보드",
        "역할",
        "팀",
        "같이",
    }
)
_CODING_PROGRESS_STATUS_PHRASES = (
    "coding progress",
    "codex progress",
    "codex status",
    "codex work session",
    "track the codex work session",
    "track codex work session",
    "coding agent status",
    "coding agent session",
    "what did the coding agent do",
    "what did the coding agent do while i was away",
    "what has the coding agent done",
    "what did codex do",
    "what did claude code do",
    "did the coding agent finish",
    "what changed in the coding agent session",
    "what changed in coding agent session",
    "tell me what changed",
    "work session and tell me what changed",
    "where is codex",
    "codex 작업",
    "codex 작업이 어디까지",
    "코덱스 작업",
    "작업이 어디까지",
    "진행됐는지",
    "진행되었는지",
)
_CODING_SESSION_STATUS_ONLY_PHRASES = (
    "session looks stuck",
    "coding session looks stuck",
    "codex session looks stuck",
    "claude code session looks stuck",
    "what is it doing",
    "what did the coding agent do",
    "what did codex do",
    "what did claude code do",
    "did the coding agent finish",
    "is codex done",
    "is claude code done",
)
_CODING_PROGRESS_STATUS_TOKENS = _normalized_token_set(
    {
        "codex",
        "claude",
        "coding",
        "agent",
        "executor",
        "progress",
        "status",
        "running",
        "session",
        "작업",
        "진행",
        "진행상황",
        "상태",
        "코덱스",
        "클로드",
        "세션",
    }
)
_GITHUB_EVENT_OPS_PHRASES = (
    "github issue to pr",
    "issue to pr",
    "issue into a pr",
    "issue should become a pr",
    "issue should become pr",
    "this issue should become a pr",
    "turn this issue into a pr",
    "make this issue into a pr",
    "convert this issue into a pr",
    "issue opened",
    "pr opened",
    "github issue",
    "github pr",
    "github issue 들어온",
)
_GITHUB_EVENT_OPS_TOKENS = _normalized_token_set(
    {
        "github",
        "issue",
        "pr",
        "pull",
        "request",
        "review",
        "ci",
        "label",
        "깃허브",
        "이슈",
        "리뷰",
        "라벨",
        "실패",
    }
)
_RELEASE_CLAIM_REVIEW_PHRASES = (
    "readme claim",
    "readme claims",
    "readme 주장",
    "claim matches actual",
    "docs match code",
    "release claim review",
    "릴리즈 전에 readme",
    "readme 주장과 실제",
    "실제 기능이 맞는지",
    "doctor/harness",
)
_RELEASE_CLAIM_REVIEW_TOKENS = _normalized_token_set(
    {
        "readme",
        "claim",
        "claims",
        "docs",
        "doctor",
        "harness",
        "release",
        "review",
        "verify",
        "검토",
        "릴리즈",
        "주장",
        "실제",
        "기능",
        "맞는지",
        "통과",
    }
)
_VOICE_OPERATOR_PHRASES = (
    "voice operator",
    "voice-first",
    "voice note",
    "mobile command",
    "from mobile",
    "on mobile",
    "from phone",
    "mobile request",
    "mobile note",
    "spoken request",
    "short voice",
    "hands free",
    "음성",
    "음성으로",
    "음성 명령",
    "짧은 명령",
    "짧게 말한 요청",
    "모바일 요청",
)
_VOICE_OPERATOR_TOKENS = _normalized_token_set(
    {
        "voice",
        "mobile",
        "spoken",
        "short",
        "terse",
        "accessibility",
        "음성",
        "모바일",
        "짧은",
        "접근성",
    }
)
_CAPABILITY_INTENT_TOKENS = _normalized_token_set(
    {
        "support",
        "supports",
        "feature",
        "features",
        "capability",
        "capabilities",
        "available",
        "help",
        "helps",
        "can",
        "기능",
        "지원",
        "가능",
        "있어",
        "있나요",
    }
)
_DELIVERABLE_STRONG_TOKENS = _normalized_token_set(
    {
        "attachment",
        "attachments",
        "attach",
        "attached",
        "deliverable",
        "deliverables",
        "첨부",
        "전달",
    }
)
_DELIVERABLE_FILE_TOKENS = _normalized_token_set(
    {
        "file",
        "files",
        "pdf",
        "ppt",
        "pptx",
        "xlsx",
        "docx",
        "hwp",
        "markdown",
        "report",
        "deck",
        "document",
        "파일",
        "보고서",
        "자료",
        "문서",
        "피디에프",
        "엑셀",
    }
)
_DELIVERABLE_PHRASES = (
    "attach file",
    "file attachment",
    "attachment status",
    "file delivery",
    "deliverable package",
    "generated file",
    "make it attachable",
    "ready to attach",
    "파일로 만들어",
    "파일로 만들어서 첨부",
    "첨부할 수 있게",
    "첨부 가능",
    "첨부 상태",
    "전달 상태",
)
_DELIVERABLE_GATEWAY_CONTEXT_TOKENS = _normalized_token_set(
    {
        "gateway",
        "platform",
        "thread",
        "silent",
        "silently",
        "discord",
        "slack",
        "telegram",
        "message",
        "messages",
        "status",
        "updates",
        "게이트웨이",
        "플랫폼",
        "스레드",
        "조용히",
        "디스코드",
        "슬랙",
        "텔레그램",
        "메시지",
        "상태",
        "업데이트",
    }
)
_DELIVERABLE_GATEWAY_CONTEXT_PHRASES = (
    "gateway thread",
    "discord gateway",
    "slack gateway",
    "telegram gateway",
    "silent attachment status",
    "silent status update",
    "status updates",
    "gateway status",
    "platform delivery",
)
_RISKY_REFACTOR_TOKENS = _normalized_token_set(
    {
        "risky",
        "risk",
        "dangerous",
        "unsafe",
        "risque",
        "risquee",
        "dangereux",
        "dangereuse",
        "peligroso",
        "peligrosa",
        "riesgoso",
        "riesgosa",
        "inseguro",
        "insegura",
        "gefahrlich",
        "gefaehrlich",
        "riskant",
        "riskante",
        "riskantes",
    }
)
_RISKY_REFACTOR_EXPLICIT_PHRASES = (
    "위험한 리팩터링",
    "위험한 리팩토링",
    "위험한 refactor",
    "위험한 refactoring",
    "리팩터링 위험",
    "리팩토링 위험",
    "refactor 위험",
    "refactoring 위험",
)
_RISKY_REFACTOR_RISK_PHRASES = (
    "feels risky",
    "seems risky",
)
_CODING_HANDOFF_EXECUTOR_TOKENS = _normalized_token_set(
    {
        "codex",
        "claude",
        "claude-code",
        "claudecode",
        "omx",
        "omo",
        "omc",
        "executor",
        "codex로",
        "codex에게",
        "claude로",
        "claude에게",
        "코덱스",
        "코덱스로",
        "코덱스에게",
        "클로드",
        "클로드로",
        "클로드에게",
    }
)
_CODING_HANDOFF_WORK_TOKENS = _normalized_token_set(
    {
        "implement",
        "implementation",
        "code",
        "coding",
        "fix",
        "issue",
        "pr",
        "feature",
        "구현",
        "코딩",
        "기능",
        "수정",
        "고쳐",
        "이슈",
    }
)
_CODING_HANDOFF_CONTROL_TOKENS = _normalized_token_set(
    {
        "delegate",
        "handoff",
        "dispatch",
        "assign",
        "track",
        "tracking",
        "status",
        "progress",
        "session",
        "attach",
        "맡기고",
        "맡기",
        "맡겨",
        "맡겨줘",
        "맡겨주세요",
        "넘기",
        "넘겨",
        "넘겨줘",
        "위임",
        "추적",
        "진행상태",
        "진행",
        "상태",
        "세션",
    }
)
_CODING_HANDOFF_PHRASES = (
    "delegate to codex",
    "send to codex",
    "codex implement",
    "codex implementation",
    "codex handoff",
    "codex progress tracking",
    "codex session tracking",
    "codex로 이 기능 구현",
    "codex로 구현 맡겨",
    "codex로 맡겨",
    "track coding progress",
    "coding agent progress",
    "open in codex",
    "attach codex session",
    "claude code handoff",
    "codex로 구현",
    "코덱스로 구현",
    "codex에게 맡기",
    "codex로 맡기",
    "코덱스에게 맡기",
    "코딩 에이전트에게 맡기",
    "구현하게 맡기고 진행상태 추적",
    "진행상태 추적",
    "진행 상태 추적",
)
_SCHEDULED_OPS_PHRASES = (
    "automation blueprint",
    "scheduled ops blueprint",
    "ops blueprint",
    "cron blueprint",
    "schedule blueprint",
    "hermes cron spec",
    "cron spec",
    "every morning",
    "every day",
    "every week",
    "every month",
    "notify if",
    "only if changed",
    "only if something changed",
    "silent if nothing changed",
    "if nothing changed",
    "매일 아침",
    "매주",
    "매월",
    "변화 있으면",
    "변화 없으면",
    "바뀐 게 없으면",
    "조용히",
)
_EXPLICIT_SCHEDULED_OPS_BLUEPRINT_PHRASES = (
    "automation blueprint",
    "scheduled ops blueprint",
    "ops blueprint",
    "cron blueprint",
    "schedule blueprint",
    "hermes cron spec",
    "cron spec",
)
_ONE_OFF_TOKENS = _normalized_token_set(
    {
        "once",
        "일회성",
        "한번만",
    }
)
_ONE_OFF_PHRASES = (
    "one-off",
    "one off",
    "one-time",
    "one time",
    "single run",
    "single-use",
    "non-recurring",
    "non recurring",
    "do not repeat",
    "dont repeat",
    "no recurrence",
    "just once",
    "only once",
    "이번만",
    "한 번만",
    "한번만",
    "일회성",
)


@dataclass(frozen=True)
class RoutingGuardRule:
    id: str
    rule: str
    matched_label: str
    preferred_skills: tuple[str, ...]
    score_boost: int
    why: str
    activation_status: str


RISKY_REFACTOR_GUARD = RoutingGuardRule(
    id="risky_refactor_before_cleanup",
    rule="Risky refactor language should route to planning/review before cleanup unless explicit invocation overrides.",
    matched_label="guard:risky_refactor_before_cleanup",
    preferred_skills=("plan", "ralplan"),
    score_boost=20,
    why="Matched guard/trigger metadata; risky code-change requests should get a reviewed plan before cleanup.",
    activation_status="active",
)
SAFE_FEATURE_PLAN_GUARD = RoutingGuardRule(
    id="safe_feature_change_before_generic_plan",
    rule="Safe feature-change requests should route to ralplan before generic planning.",
    matched_label="guard:safe_feature_change",
    preferred_skills=("ralplan",),
    score_boost=32,
    why="Matched safe feature-change language; prepare a reviewed plan before executor handoff.",
    activation_status="active",
)
FEEDBACK_BEFORE_CODING_GUARD = RoutingGuardRule(
    id="feedback_before_coding",
    rule="Product feedback and bug reports should route through triage/investigation before coding handoff unless code work is explicit.",
    matched_label="guard:feedback_before_coding",
    preferred_skills=("feedback-triage",),
    score_boost=34,
    why="Matched customer or product signal language; triage the signal and investigation path before planning fixes.",
    activation_status="active",
)
PRODUCT_SHAPING_GUARD = RoutingGuardRule(
    id="product_shaping_before_ops_review",
    rule="Fuzzy product, onboarding, UX, or growth-shaping requests should start with deep interview before ops/status review.",
    matched_label="guard:product_shaping",
    preferred_skills=("deep-interview",),
    score_boost=30,
    why="Matched guard/trigger metadata; fuzzy product-shaping requests need one clarifying interview before plan or execution.",
    activation_status="active",
)
WORKFLOW_LEARNING_GUARD = RoutingGuardRule(
    id="workflow_learning_before_skill_management",
    rule="Requests to learn from a workflow, improve a skill next time, or add routing regressions should route to workflow-learning before generic skill management.",
    matched_label="guard:workflow_learning",
    preferred_skills=("workflow-learning",),
    score_boost=34,
    why="Matched guard/trigger metadata; workflow improvement requests should become a learning trace, review candidate, or regression instead of generic skill management.",
    activation_status="active",
)
OMH_QUALITY_IMPROVEMENT_GUARD = RoutingGuardRule(
    id="omh_quality_improvement_loop_before_feedback_triage",
    rule=(
        "OMH self-improvement requests about router quality, context loss, progress reporting, or coding-handoff "
        "reliability should route to the process/coding lane even when bug words are present."
    ),
    matched_label="guard:omh_quality_improvement_loop",
    preferred_skills=("ultraprocess",),
    score_boost=48,
    why=(
        "Matched semantic OMH quality-improvement intent; bug/failure terms are evidence for improving OMH "
        "routing/context/handoff behavior, not customer feedback triage."
    ),
    activation_status="active",
)
PERSISTENT_COMPLETION_GUARD = RoutingGuardRule(
    id="persistent_completion_before_board_status",
    rule="Persistent finish-until-pass-or-block requests should route to ralph before board/status surfaces.",
    matched_label="guard:persistent_completion",
    preferred_skills=("ralph",),
    score_boost=38,
    why="Matched completion-loop language with a concrete pass/block stop condition.",
    activation_status="active",
)
RESEARCH_BRIEF_GUARD = RoutingGuardRule(
    id="research_brief_before_wiki",
    rule="Comparison and evidence-gap research synthesis should route to research-brief before durable wiki capture.",
    matched_label="guard:research_brief",
    preferred_skills=("research-brief",),
    score_boost=38,
    why="Matched comparison research with evidence, confidence, or notes; prepare a brief before capturing knowledge.",
    activation_status="active",
)
STRATEGY_BRIEF_GUARD = RoutingGuardRule(
    id="strategy_brief_before_generic_plan",
    rule="Business prioritization and segment decisions should route to strategy-brief before generic planning.",
    matched_label="guard:strategy_brief",
    preferred_skills=("strategy-brief",),
    score_boost=40,
    why="Matched strategy decision language; prepare options and tradeoffs before implementation planning.",
    activation_status="active",
)
APP_DELIVERY_LOOP_GUARD = RoutingGuardRule(
    id="app_delivery_loop_before_generic_plan",
    rule="Idea-to-release paths should route to idea-to-deploy before generic planning.",
    matched_label="guard:app_delivery_loop",
    preferred_skills=("idea-to-deploy",),
    score_boost=38,
    why="Matched idea, handoff, QA, and release path language; use the app delivery loop surface.",
    activation_status="active",
)
CTO_LOOP_GUARD = RoutingGuardRule(
    id="cto_loop_before_generic_loop",
    rule="PM/dev/QA/security/ops leadership loops should route to cto-loop before generic loop handling.",
    matched_label="guard:cto_loop",
    preferred_skills=("cto-loop",),
    score_boost=48,
    why="Matched leadership role loop language; prepare the CTO operating model rather than a generic loop.",
    activation_status="active",
)
ADVERSARIAL_QA_GUARD = RoutingGuardRule(
    id="adversarial_qa_before_generic_help",
    rule="Hostile, adversarial, missing-path, or stale-config testing requests should route to ultraqa.",
    matched_label="guard:adversarial_qa",
    preferred_skills=("ultraqa",),
    score_boost=42,
    why="Matched adversarial QA scenario language; route to the QA harness instead of generic help.",
    activation_status="active",
)
CLEANUP_REFACTOR_GUARD = RoutingGuardRule(
    id="cleanup_refactor_before_workflow_learning",
    rule="Code cleanup/refactor requests with regression-test language should route to ai-slop-cleaner before workflow-learning.",
    matched_label="guard:cleanup_refactor",
    preferred_skills=("ai-slop-cleaner",),
    score_boost=50,
    why="Matched concrete cleanup/refactor work with behavior-locking tests; use the cleanup harness rather than process learning.",
    activation_status="active",
)
DURABLE_RESEARCH_GUARD = RoutingGuardRule(
    id="durable_research_goal_before_wiki",
    rule="Keep-researching-until-gap-closed requests should route to autoresearch-goal before wiki capture.",
    matched_label="guard:durable_research_goal",
    preferred_skills=("autoresearch-goal",),
    score_boost=44,
    why="Matched durable research loop language with evidence gaps and a stop condition.",
    activation_status="active",
)
WEB_RESEARCH_BEFORE_PROCESS_GUARD = RoutingGuardRule(
    id="web_research_before_process",
    rule="Plain web/source/current-evidence requests should route to web research before one-cycle delivery.",
    matched_label="guard:web_research_before_process",
    preferred_skills=("web-research",),
    score_boost=14,
    why="Matched guard/trigger metadata; web, source, or freshness requests should start with source-backed Hermes research.",
    activation_status="active",
)
SOURCE_FINDER_GUARD = RoutingGuardRule(
    id="source_finder_before_generic_web_research",
    rule="Typed source candidate acquisition should route to source-finder before generic web research.",
    matched_label="guard:source_finder",
    preferred_skills=("source-finder",),
    score_boost=36,
    why="Matched guard/trigger metadata; typed source acquisition should prepare candidates, acquisition state, and downstream routing before evidence synthesis.",
    activation_status="active",
)
MISSED_WORKFLOW_WEB_RESEARCH_GUARD = RoutingGuardRule(
    id="missed_workflow_research_recovery",
    rule="Missed-OMH feedback about research/source work should recover to web-research instead of broad router help.",
    matched_label="guard:missed_workflow_research_recovery",
    preferred_skills=("web-research",),
    score_boost=32,
    why="Matched guard/trigger metadata; missed OMH research feedback should recover to source-backed Hermes research.",
    activation_status="active",
)
MISSED_WORKFLOW_OPERATING_RHYTHM_GUARD = RoutingGuardRule(
    id="missed_workflow_operating_record_recovery",
    rule="Missed-OMH feedback about meeting notes or operating records should recover to operating-rhythm.",
    matched_label="guard:missed_workflow_operating_record_recovery",
    preferred_skills=("operating-rhythm",),
    score_boost=34,
    why="Matched guard/trigger metadata; missed OMH meeting/record feedback should prepare an operating record with evidence boundaries.",
    activation_status="active",
)
DELIVERY_CYCLE_GUARD = RoutingGuardRule(
    id="delivery_cycle_before_research_only",
    rule="Requests that ask for PR or delivery-cycle completion should route to Ultraprocess before research-only lanes.",
    matched_label="guard:delivery_cycle_before_research_only",
    preferred_skills=("ultraprocess",),
    score_boost=12,
    why="Matched guard/trigger metadata; PR or delivery-cycle requests need the one-cycle process lane rather than research-only routing.",
    activation_status="active",
)
CODING_HANDOFF_STATUS_GUARD = RoutingGuardRule(
    id="coding_handoff_status_before_clarify",
    rule="Executor-named coding handoff plus progress/status tracking should route to Ultraprocess instead of generic clarification.",
    matched_label="guard:coding_handoff_status",
    preferred_skills=("ultraprocess",),
    score_boost=26,
    why="Matched guard/trigger metadata; executor-named coding handoff and status requests should prepare a tracked one-cycle handoff without claiming execution.",
    activation_status="active",
)
EXECUTOR_RUNTIME_READINESS_GUARD = RoutingGuardRule(
    id="executor_runtime_readiness_before_generic_advice",
    rule="Executor/runtime comparison requests should route to executor-runtime-readiness before generic advice.",
    matched_label="guard:executor_runtime_readiness",
    preferred_skills=("executor-runtime-readiness",),
    score_boost=30,
    why="Matched guard/trigger metadata; executor/runtime comparison should show tool gaps and handoff mode before selection.",
    activation_status="active",
)
MATERIALS_PACKAGE_GUARD = RoutingGuardRule(
    id="materials_package_before_report_or_clarify",
    rule="Multi-format document, spreadsheet, deck, or PDF packaging requests should route to materials-package before generic report planning.",
    matched_label="guard:materials_package",
    preferred_skills=("materials-package",),
    score_boost=24,
    why="Matched guard/trigger metadata; material processing requests should prepare a target-format package and QA ladder.",
    activation_status="active",
)
MEMORY_CURATION_GUARD = RoutingGuardRule(
    id="memory_curation_before_generic_clarification",
    rule="Hermes memory/context cleanup requests should route to memory-curation-review before generic clarification.",
    matched_label="guard:memory_curation",
    preferred_skills=("memory-curation-review",),
    score_boost=28,
    why="Matched guard/trigger metadata; stale or conflicting Hermes context should become a human-approved memory curation review.",
    activation_status="active",
)
AGENT_BOARD_GUARD = RoutingGuardRule(
    id="agent_board_before_generic_clarification",
    rule="Multi-agent role, board, kanban, heartbeat, or blocker coordination requests should route to agent-board.",
    matched_label="guard:agent_board",
    preferred_skills=("agent-board",),
    score_boost=26,
    why="Matched guard/trigger metadata; multiple Hermes targets need a board/status contract before work is claimed.",
    activation_status="active",
)
CODING_PROGRESS_STATUS_GUARD = RoutingGuardRule(
    id="coding_progress_status_before_clarify",
    rule="Executor or coding-agent progress/status requests should route to agent-ops-review before generic clarification.",
    matched_label="guard:coding_progress_status",
    preferred_skills=("agent-ops-review",),
    score_boost=28,
    why="Matched guard/trigger metadata; coding progress questions should render a manager-facing status card with observed gaps.",
    activation_status="active",
)
GITHUB_EVENT_OPS_GUARD = RoutingGuardRule(
    id="github_event_ops_before_generic_planning",
    rule="GitHub PR, issue, CI, and issue-to-PR requests should route to github-event-ops before generic planning.",
    matched_label="guard:github_event_ops",
    preferred_skills=("github-event-ops",),
    score_boost=24,
    why="Matched guard/trigger metadata; GitHub event and issue-to-PR requests should create an event ops card before plan or handoff claims.",
    activation_status="active",
)
RELEASE_CLAIM_REVIEW_GUARD = RoutingGuardRule(
    id="release_claim_review_before_file_lookup",
    rule="Release claim and README-vs-code review requests should route to review before file lookup fallback.",
    matched_label="guard:release_claim_review",
    preferred_skills=("code-review",),
    score_boost=20,
    why="Matched guard/trigger metadata; release claim checks need review boundaries instead of plain file lookup.",
    activation_status="active",
)
DOCTOR_HEALTH_GUARD = RoutingGuardRule(
    id="doctor_health_before_skill_catalog",
    rule="OMH install, setup, update, stale skill, or registration health confusion should route to doctor.",
    matched_label="guard:doctor_health",
    preferred_skills=("doctor",),
    score_boost=30,
    why="Matched guard/trigger metadata; setup/update health confusion should run diagnostics before skill catalog management.",
    activation_status="active",
)
VOICE_OPERATOR_GUARD = RoutingGuardRule(
    id="voice_operator_before_generic_clarification",
    rule="Voice, mobile, or terse accessibility-sensitive requests should route to voice-operator before generic clarification.",
    matched_label="guard:voice_operator",
    preferred_skills=("voice-operator",),
    score_boost=24,
    why="Matched guard/trigger metadata; voice/mobile-style requests need concise clarify/plan/status UX with confirmation boundaries.",
    activation_status="active",
)
VISUAL_SUMMARY_GUARD = RoutingGuardRule(
    id="img_summary_before_materials_or_delivery",
    rule="Image, card, or img-summary requests should route to img-summary before materials or PR delivery-cycle lanes.",
    matched_label="guard:img_summary",
    preferred_skills=("img-summary",),
    score_boost=30,
    why="Matched guard/trigger metadata; visual image-card requests should prepare a visual prompt card before delivery or material packaging.",
    activation_status="active",
)
DELIVERABLE_PACKAGE_GUARD = RoutingGuardRule(
    id="deliverable_package_for_file_attachment",
    rule="Requests that combine generated files or reports with attachment/delivery status should route to deliverable-package.",
    matched_label="guard:deliverable_package",
    preferred_skills=("deliverable-package",),
    score_boost=28,
    why="Matched guard/trigger metadata; file attachment or delivery-status requests should prepare a deliverable package before claiming output.",
    activation_status="active",
)
SCHEDULED_OPS_BLUEPRINT_GUARD = RoutingGuardRule(
    id="scheduled_ops_blueprint_before_reliability_or_research",
    rule="Recurring schedule, delivery, or silence-policy requests should route to the scheduled ops blueprint lane before one-off review/research lanes.",
    matched_label="guard:scheduled_ops_blueprint",
    preferred_skills=("automation-blueprint",),
    score_boost=24,
    why="Matched guard/trigger metadata; recurring schedule or delivery requests should prepare a Hermes ops blueprint first.",
    activation_status="active",
)
RESEARCH_DEPARTMENT_GUARD = RoutingGuardRule(
    id="research_department_before_generic_scheduled_ops",
    rule="Recurring or durable research operations should route to the research department workflow pack before generic scheduled ops.",
    matched_label="guard:research_department",
    preferred_skills=("research-department",),
    score_boost=40,
    why="Matched guard/trigger metadata; recurring research operations should prepare a Scout/Analyst/Briefer research department plan.",
    activation_status="active",
)
PAPER_LEARNING_GUARD = RoutingGuardRule(
    id="paper_learning_before_materials_or_research_ops",
    rule="One-off paper or paper-PDF explanation requests should route to paper-learning before generic file packaging or research ops.",
    matched_label="guard:paper_learning",
    preferred_skills=("paper-learning",),
    score_boost=42,
    why="Matched guard/trigger metadata; paper explanation requests need level selection, source-state evidence, and a coverage ledger.",
    activation_status="active",
)
ROUTING_GUARD_RULES = (
    RISKY_REFACTOR_GUARD,
    SAFE_FEATURE_PLAN_GUARD,
    FEEDBACK_BEFORE_CODING_GUARD,
    PRODUCT_SHAPING_GUARD,
    PERSISTENT_COMPLETION_GUARD,
    RESEARCH_BRIEF_GUARD,
    STRATEGY_BRIEF_GUARD,
    APP_DELIVERY_LOOP_GUARD,
    CTO_LOOP_GUARD,
    ADVERSARIAL_QA_GUARD,
    CLEANUP_REFACTOR_GUARD,
    DURABLE_RESEARCH_GUARD,
    WORKFLOW_LEARNING_GUARD,
    OMH_QUALITY_IMPROVEMENT_GUARD,
    PAPER_LEARNING_GUARD,
    RESEARCH_DEPARTMENT_GUARD,
    SCHEDULED_OPS_BLUEPRINT_GUARD,
    SOURCE_FINDER_GUARD,
    WEB_RESEARCH_BEFORE_PROCESS_GUARD,
    MISSED_WORKFLOW_WEB_RESEARCH_GUARD,
    MISSED_WORKFLOW_OPERATING_RHYTHM_GUARD,
    GITHUB_EVENT_OPS_GUARD,
    MATERIALS_PACKAGE_GUARD,
    MEMORY_CURATION_GUARD,
    AGENT_BOARD_GUARD,
    CODING_PROGRESS_STATUS_GUARD,
    RELEASE_CLAIM_REVIEW_GUARD,
    DOCTOR_HEALTH_GUARD,
    EXECUTOR_RUNTIME_READINESS_GUARD,
    VOICE_OPERATOR_GUARD,
    VISUAL_SUMMARY_GUARD,
    DELIVERABLE_PACKAGE_GUARD,
    DELIVERY_CYCLE_GUARD,
    CODING_HANDOFF_STATUS_GUARD,
)


def is_ambiguous_scores(first_score: int, second_score: int | None) -> bool:
    return second_score is not None and first_score > 0 and first_score == second_score


def meets_confidence_threshold(confidence: str, threshold: str) -> bool:
    return _CONFIDENCE_RANK[confidence] >= _CONFIDENCE_RANK[threshold]


def explicit_skill_invocation(message: str, names: set[str]) -> str | None:
    first = message.strip().split(maxsplit=1)[0].strip(":,").lower()
    used_prefix = False
    for prefix in sorted(EXPLICIT_INVOCATION_PREFIXES, key=len, reverse=True):
        if first.startswith(prefix):
            first = first[len(prefix) :].strip(":,")
            used_prefix = True
            break
    if first in names:
        return first
    alias = _EXPLICIT_SKILL_ALIASES.get(first)
    if alias in names:
        return alias
    if used_prefix:
        alias = _PREFIXED_SKILL_ALIASES.get(first)
        if alias in names:
            return alias
    return None


def active_routing_guard_rules(
    normalized_query: str,
    query_tokens: set[str],
    *,
    explicit_skill: str | None = None,
) -> tuple[RoutingGuardRule, ...]:
    if explicit_skill:
        return ()
    rules: list[RoutingGuardRule] = []
    if _risky_refactor_guard_applies(normalized_query, query_tokens):
        rules.append(RISKY_REFACTOR_GUARD)
    if _safe_feature_plan_guard_applies(normalized_query, query_tokens):
        rules.append(SAFE_FEATURE_PLAN_GUARD)
    if _feedback_before_coding_guard_applies(normalized_query, query_tokens):
        rules.append(FEEDBACK_BEFORE_CODING_GUARD)
    if _product_shaping_guard_applies(normalized_query, query_tokens):
        rules.append(PRODUCT_SHAPING_GUARD)
    if _persistent_completion_guard_applies(normalized_query, query_tokens):
        rules.append(PERSISTENT_COMPLETION_GUARD)
    if _research_brief_guard_applies(normalized_query, query_tokens):
        rules.append(RESEARCH_BRIEF_GUARD)
    if _strategy_brief_guard_applies(normalized_query, query_tokens):
        rules.append(STRATEGY_BRIEF_GUARD)
    if _app_delivery_loop_guard_applies(normalized_query, query_tokens):
        rules.append(APP_DELIVERY_LOOP_GUARD)
    if _cto_loop_guard_applies(normalized_query, query_tokens):
        rules.append(CTO_LOOP_GUARD)
    if _adversarial_qa_guard_applies(normalized_query, query_tokens):
        rules.append(ADVERSARIAL_QA_GUARD)
    if _cleanup_refactor_guard_applies(normalized_query, query_tokens):
        rules.append(CLEANUP_REFACTOR_GUARD)
    if _durable_research_goal_guard_applies(normalized_query, query_tokens):
        rules.append(DURABLE_RESEARCH_GUARD)
    workflow_learning_applies = _workflow_learning_guard_applies(normalized_query, query_tokens)
    if workflow_learning_applies:
        rules.append(WORKFLOW_LEARNING_GUARD)
    if not workflow_learning_applies and _omh_quality_improvement_guard_applies(normalized_query):
        rules.append(OMH_QUALITY_IMPROVEMENT_GUARD)
    delivery_cycle_applies = _delivery_cycle_guard_applies(normalized_query, query_tokens)
    paper_learning_applies = (
        not delivery_cycle_applies and _paper_learning_guard_applies(normalized_query, query_tokens)
    )
    if paper_learning_applies:
        rules.append(PAPER_LEARNING_GUARD)
    scheduled_ops_blueprint_applies = (
        not delivery_cycle_applies and _scheduled_ops_blueprint_guard_applies(normalized_query, query_tokens)
    )
    explicit_scheduled_ops_blueprint = _explicit_scheduled_ops_blueprint_requested(normalized_query, query_tokens)
    research_department_applies = (
        not delivery_cycle_applies
        and not paper_learning_applies
        and not explicit_scheduled_ops_blueprint
        and _research_department_guard_applies(normalized_query, query_tokens)
    )
    if research_department_applies:
        rules.append(RESEARCH_DEPARTMENT_GUARD)
    if (
        scheduled_ops_blueprint_applies
        and (explicit_scheduled_ops_blueprint or not research_department_applies)
    ):
        rules.append(SCHEDULED_OPS_BLUEPRINT_GUARD)
    source_finder_applies = (
        not delivery_cycle_applies
        and not paper_learning_applies
        and not research_department_applies
        and _source_finder_guard_applies(normalized_query, query_tokens)
    )
    if source_finder_applies:
        rules.append(SOURCE_FINDER_GUARD)
    if _missed_workflow_operating_record_guard_applies(normalized_query, query_tokens):
        rules.append(MISSED_WORKFLOW_OPERATING_RHYTHM_GUARD)
    if _web_research_guard_applies(normalized_query, query_tokens) and not paper_learning_applies and not source_finder_applies:
        rules.append(WEB_RESEARCH_BEFORE_PROCESS_GUARD)
    if _missed_workflow_research_guard_applies(normalized_query, query_tokens):
        rules.append(MISSED_WORKFLOW_WEB_RESEARCH_GUARD)
    if _github_event_ops_guard_applies(normalized_query, query_tokens):
        rules.append(GITHUB_EVENT_OPS_GUARD)
    deliverable_package_applies = _deliverable_package_guard_applies(normalized_query, query_tokens)
    if (
        _materials_package_guard_applies(normalized_query, query_tokens)
        and not paper_learning_applies
        and not deliverable_package_applies
    ):
        rules.append(MATERIALS_PACKAGE_GUARD)
    if _memory_curation_guard_applies(normalized_query, query_tokens):
        rules.append(MEMORY_CURATION_GUARD)
    if _agent_board_guard_applies(normalized_query, query_tokens):
        rules.append(AGENT_BOARD_GUARD)
    if _coding_progress_status_guard_applies(normalized_query, query_tokens):
        rules.append(CODING_PROGRESS_STATUS_GUARD)
    if _release_claim_review_guard_applies(normalized_query, query_tokens):
        rules.append(RELEASE_CLAIM_REVIEW_GUARD)
    if _doctor_health_guard_applies(normalized_query, query_tokens):
        rules.append(DOCTOR_HEALTH_GUARD)
    if _executor_runtime_readiness_guard_applies(normalized_query, query_tokens):
        rules.append(EXECUTOR_RUNTIME_READINESS_GUARD)
    if _voice_operator_guard_applies(normalized_query, query_tokens):
        rules.append(VOICE_OPERATOR_GUARD)
    if _visual_summary_guard_applies(normalized_query, query_tokens):
        rules.append(VISUAL_SUMMARY_GUARD)
    if deliverable_package_applies:
        rules.append(DELIVERABLE_PACKAGE_GUARD)
    if _coding_handoff_status_guard_applies(normalized_query, query_tokens):
        rules.append(CODING_HANDOFF_STATUS_GUARD)
    if delivery_cycle_applies:
        rules.append(DELIVERY_CYCLE_GUARD)
    return tuple(rules)


def _risky_refactor_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _contains_phrase(normalized_query, _RISKY_REFACTOR_EXPLICIT_PHRASES):
        return True
    if not ({"refactor", "refactoring"} & query_tokens):
        return False
    if _RISKY_REFACTOR_TOKENS & query_tokens:
        return True
    return _contains_phrase(normalized_query, _RISKY_REFACTOR_RISK_PHRASES)


def _product_shaping_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _delivery_cycle_terms(normalized_query, query_tokens):
        return False
    if _contains_phrase(normalized_query, _PRODUCT_SHAPING_PHRASES):
        return True
    product_context = bool(_PRODUCT_SHAPING_CONTEXT_TOKENS & query_tokens)
    shaping_uncertainty = bool(_PRODUCT_SHAPING_UNCERTAINTY_TOKENS & query_tokens)
    return product_context and shaping_uncertainty


def _feedback_before_coding_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _github_event_ops_guard_applies(normalized_query, query_tokens):
        return False
    if _doctor_health_guard_applies(normalized_query, query_tokens):
        return False
    if _explicit_delivery_or_implementation_requested(normalized_query, query_tokens):
        return False
    if _contains_phrase(normalized_query, _FEEDBACK_TRIAGE_PHRASES):
        return True
    source_signal = bool(_FEEDBACK_TRIAGE_SOURCE_TOKENS & query_tokens)
    product_context = bool(_FEEDBACK_TRIAGE_PRODUCT_TOKENS & query_tokens)
    issue_signal = bool(_FEEDBACK_TRIAGE_ISSUE_TOKENS & query_tokens)
    decision_signal = bool(_FEEDBACK_TRIAGE_DECISION_TOKENS & query_tokens)
    return (source_signal and (issue_signal or decision_signal)) or (product_context and issue_signal)


def _workflow_learning_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _contains_phrase(normalized_query, _WORKFLOW_LEARNING_PHRASES):
        return True
    learning = bool({"learn", "learning", "학습"} & query_tokens)
    workflow_or_skill = bool({"workflow", "run", "trace", "skill", "routing", "route", "워크플로우", "스킬", "라우팅"} & query_tokens)
    future_improvement = bool({"improve", "improvement", "next", "future", "regression", "개선", "회귀"} & query_tokens)
    feedback_action = bool(_WORKFLOW_LEARNING_ACTION_TOKENS & query_tokens)
    if learning and workflow_or_skill and feedback_action:
        return True
    if future_improvement and workflow_or_skill and bool(_WORKFLOW_LEARNING_CONTEXT_TOKENS & query_tokens):
        return True
    return False


def _omh_quality_improvement_guard_applies(normalized_query: str) -> bool:
    return classify_omh_quality_intent(normalized_query).applies


def _safe_feature_plan_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    safe_signal = bool({"safe", "safely", "safety", "안전", "안전하게"} & query_tokens) or _contains_phrase(
        normalized_query,
        ("safe feature", "safely add a feature", "safe plan", "안전하게 기능", "안전한 기능"),
    )
    feature_change = bool({"feature", "features", "기능"} & query_tokens) and (
        bool({"add", "implement", "change", "build", "추가", "구현"} & query_tokens)
        or _contains_phrase(normalized_query, ("add a feature", "feature change", "기능 추가"))
    )
    scope_or_handoff = bool({"repo", "repository", "handoff", "plan", "codebase", "executor"} & query_tokens) or _contains_phrase(
        normalized_query,
        ("this repo", "this repository", "before handoff", "request-to-handoff", "코드베이스", "핸드오프"),
    )
    return safe_signal and feature_change and scope_or_handoff


def _persistent_completion_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    completion = _contains_phrase(
        normalized_query,
        (
            "finish until",
            "until done",
            "until the smoke test passes",
            "until smoke test passes",
            "until the test passes",
            "until tests pass",
            "until a blocker",
            "or a blocker is recorded",
            "blocker is recorded",
        ),
    )
    pass_or_block = bool({"pass", "passes", "blocker", "blocked", "done"} & query_tokens) or _contains_phrase(
        normalized_query,
        ("smoke test", "stop condition", "completion owner", "완료될 때까지", "막히면"),
    )
    return completion and pass_or_block


def _research_brief_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _research_department_guard_applies(normalized_query, query_tokens):
        return False
    compare = bool({"compare", "comparison", "benchmark", "evaluate", "vendors", "vendor"} & query_tokens)
    evidence = bool({"notes", "evidence", "confidence", "gaps", "sources", "customer"} & query_tokens)
    research_subject = bool({"vendor", "vendors", "market", "competitor", "analytics", "customer"} & query_tokens)
    phrase = _contains_phrase(
        normalized_query,
        (
            "compare three",
            "compare vendors",
            "compare products",
            "using customer notes",
            "confidence gaps",
            "research brief",
        ),
    )
    return phrase or (compare and research_subject and evidence)


def _strategy_brief_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    strategy_action = bool({"decide", "prioritize", "strategy", "positioning", "choose"} & query_tokens)
    business_target = bool(
        {
            "buyers",
            "segments",
            "enterprise",
            "founders",
            "market",
            "onboarding",
            "pricing",
            "positioning",
            "roadmap",
        }
        & query_tokens
    )
    tradeoff = _contains_phrase(
        normalized_query,
        ("whether", "or", "rather than", "prioritize", "decide whether", "전략", "우선순위", "결정"),
    )
    return strategy_action and business_target and tradeoff


def _app_delivery_loop_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    idea = "idea" in query_tokens or _contains_phrase(normalized_query, ("this idea", "feature idea", "제품 아이디어"))
    path = _contains_phrase(
        normalized_query,
        (
            "scoped plan",
            "implementation handoff",
            "qa gate",
            "release path",
            "idea to deploy",
            "idea-to-deploy",
        ),
    )
    delivery_terms = len({"plan", "handoff", "qa", "release", "deploy"} & query_tokens) >= 3
    return idea and (path or delivery_terms)


def _cto_loop_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _contains_phrase(normalized_query, ("cto loop", "cto-loop", "cto operating model")):
        return True
    role_names = ("pm", "cto", "dev", "qa", "security", "ops")
    named_roles = {role for role in role_names if role in query_tokens or _contains_phrase(normalized_query, (role,))}
    launch_or_risk = bool({"launch", "release", "billing", "risky", "risk"} & query_tokens)
    loop = "loop" in query_tokens or _contains_phrase(normalized_query, ("operating loop", "leadership loop"))
    return len(named_roles) >= 4 and loop and launch_or_risk


def _adversarial_qa_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    qa_context = bool({"test", "tests", "qa", "wizard"} & query_tokens)
    adversarial = bool({"hostile", "adversarial", "stale", "missing", "invalid", "broken"} & query_tokens)
    scenario_phrase = _contains_phrase(
        normalized_query,
        (
            "hostile install",
            "hostile paths",
            "stale config",
            "missing path",
            "missing PATH",
            "adversarial qa",
            "hostile cases",
        ),
    )
    return qa_context and (adversarial or scenario_phrase)


def _cleanup_refactor_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    cleanup = bool({"cleanup", "clean", "remove", "dedupe", "deduplicate", "simplify", "refactor", "refactoring"} & query_tokens)
    code_surface = bool({"code", "router", "routing", "branches", "implementation"} & query_tokens)
    behavior_lock = bool({"regression", "tests", "test", "behavior"} & query_tokens) or _contains_phrase(
        normalized_query,
        ("lock behavior", "regression tests", "before refactoring"),
    )
    phrase = _contains_phrase(
        normalized_query,
        ("remove duplicated", "remove duplicate", "clean up duplicated", "cleanup duplicated", "duplicated router"),
    )
    return (cleanup or phrase) and code_surface and behavior_lock


def _durable_research_goal_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    durable = _contains_phrase(
        normalized_query,
        (
            "keep researching",
            "continue researching",
            "until the evidence gaps are closed",
            "until evidence gaps are closed",
            "evidence gaps are closed or logged",
            "durable research",
        ),
    )
    research = bool({"research", "researching", "evidence", "gaps", "sources"} & query_tokens)
    stop_condition = _contains_phrase(normalized_query, ("until", "closed or logged", "checkpoint", "stop condition"))
    return durable and research and stop_condition


def _scheduled_ops_blueprint_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if is_explicit_one_off_request(normalized_query, query_tokens):
        return False
    if _SCHEDULED_OPS_STRONG_TOKENS & query_tokens:
        return True
    if _SCHEDULED_OPS_CADENCE_TOKENS & query_tokens and _SCHEDULED_OPS_CONTEXT_TOKENS & query_tokens:
        return True
    return _contains_phrase(normalized_query, _SCHEDULED_OPS_PHRASES)


def _explicit_scheduled_ops_blueprint_requested(normalized_query: str, query_tokens: set[str]) -> bool:
    if _contains_phrase(normalized_query, _EXPLICIT_SCHEDULED_OPS_BLUEPRINT_PHRASES):
        return True
    blueprint = "blueprint" in query_tokens
    scheduled_context = bool(_SCHEDULED_OPS_STRONG_TOKENS & query_tokens) or bool(
        _SCHEDULED_OPS_CADENCE_TOKENS & query_tokens
    )
    return blueprint and scheduled_context


def _paper_learning_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _visual_summary_guard_applies(normalized_query, query_tokens):
        return False
    if _explicit_material_export_requested(normalized_query, query_tokens):
        return False
    if _paper_validation_or_citation_requested(normalized_query, query_tokens):
        return False
    if _scheduled_ops_blueprint_guard_applies(normalized_query, query_tokens):
        recurring_paper_ops = bool(_PAPER_LEARNING_PAPER_TOKENS & query_tokens) or _contains_phrase(
            normalized_query, ("paper", "논문")
        )
        if recurring_paper_ops and not bool(_PAPER_LEARNING_EXPLANATION_TOKENS & query_tokens):
            return False
    if _contains_phrase(normalized_query, _PAPER_LEARNING_PHRASES):
        return True
    paper_context = bool(_PAPER_LEARNING_PAPER_TOKENS & query_tokens) or _contains_phrase(
        normalized_query,
        ("research paper", "arxiv paper", "paper pdf", "pdf paper", "논문 pdf"),
    )
    explanation_context = bool(_PAPER_LEARNING_EXPLANATION_TOKENS & query_tokens) or _contains_phrase(
        normalized_query,
        ("explain", "walk through", "walkthrough", "without dropping details", "내용 줄이지", "설명해줘", "해설해줘"),
    )
    search_only = bool({"find", "search", "latest", "current", "fresh"} & query_tokens) or _contains_phrase(
        normalized_query,
        ("find papers", "search papers", "latest papers", "current papers", "논문 찾아", "최신 논문"),
    )
    return paper_context and explanation_context and not search_only


def _paper_validation_or_citation_requested(normalized_query: str, query_tokens: set[str]) -> bool:
    if _contains_phrase(normalized_query, _PAPER_LEARNING_VALIDATION_PHRASES):
        return True
    validation_tokens = {"verify", "validate", "factcheck", "citation", "citations", "proof", "reproduce"}
    paper_context = bool(_PAPER_LEARNING_PAPER_TOKENS & query_tokens) or _contains_phrase(
        normalized_query,
        ("paper", "arxiv", "논문"),
    )
    return paper_context and bool(validation_tokens & query_tokens)


def _explicit_material_export_requested(normalized_query: str, query_tokens: set[str]) -> bool:
    if _contains_phrase(normalized_query, _PAPER_LEARNING_EXPORT_PHRASES):
        return True
    action = bool(_MATERIALS_PACKAGE_ACTION_TOKENS & query_tokens) or _contains_phrase(
        normalized_query,
        ("make", "turn into", "prepare", "export", "package", "만들", "변환"),
    )
    if not action:
        return False
    output_formats = _MATERIALS_PACKAGE_FORMAT_TOKENS & query_tokens
    non_source_pdf_formats = {
        "ppt",
        "pptx",
        "spreadsheet",
        "excel",
        "xlsx",
        "docx",
        "hwp",
        "document",
        "엑셀",
        "문서",
        "자료",
        "첨부",
    }
    if output_formats & non_source_pdf_formats:
        return True
    return _contains_phrase(
        normalized_query,
        (
            "export a pdf",
            "export pdf",
            "as a pdf",
            "make a pdf",
            "create a pdf",
            "package it as a pdf",
            "pdf로 만들",
            "pdf로 변환",
        ),
    )


def _research_department_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if is_explicit_one_off_request(normalized_query, query_tokens):
        return False
    recurring = (
        _scheduled_ops_blueprint_guard_applies(normalized_query, query_tokens)
        or bool({"ongoing", "durable", "24", "daily", "weekly", "monthly", "매일", "매주"} & query_tokens)
        or _contains_phrase(normalized_query, ("ongoing", "durable", "daily", "weekly", "monthly", "매일", "매주"))
    )
    support = bool(_RESEARCH_DEPARTMENT_SUPPORT_TOKENS & query_tokens) or _contains_phrase(
        normalized_query, _RESEARCH_DEPARTMENT_SUPPORT_TOKENS
    )
    specific_research_domain = (
        bool((_RESEARCH_DEPARTMENT_STRONG_TOKENS - {"research", "리서치", "조사"}) & query_tokens)
        or _contains_phrase(normalized_query, ("경쟁사", "시장", "논문"))
    )
    generic_research = bool({"research", "리서치", "조사"} & query_tokens)
    research = (
        specific_research_domain
        or (generic_research and support)
        or _contains_phrase(normalized_query, _RESEARCH_DEPARTMENT_PHRASES)
    )
    explicit_research_ops = _contains_phrase(normalized_query, _RESEARCH_DEPARTMENT_PHRASES)
    return recurring and research and (support or specific_research_domain or explicit_research_ops)


def _source_finder_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _visual_summary_guard_applies(normalized_query, query_tokens):
        return False
    if _explicit_material_export_requested(normalized_query, query_tokens):
        return False
    if _paper_learning_guard_applies(normalized_query, query_tokens):
        return False
    if _research_department_guard_applies(normalized_query, query_tokens):
        return False
    if _scheduled_ops_blueprint_guard_applies(normalized_query, query_tokens):
        return False
    if _contains_phrase(normalized_query, _SOURCE_FINDER_EXCLUSION_PHRASES):
        return False
    if _paper_validation_or_citation_requested(normalized_query, query_tokens):
        return False
    if _contains_phrase(normalized_query, _SOURCE_FINDER_PHRASES):
        return True
    action = bool(_SOURCE_FINDER_ACTION_TOKENS & query_tokens)
    source_kind = bool(_SOURCE_FINDER_KIND_TOKENS & query_tokens)
    multiple_source_kinds = len(_SOURCE_FINDER_KIND_TOKENS & query_tokens) >= 2
    acquisition_noun = _contains_phrase(
        normalized_query,
        ("source candidate", "source candidates", "downloadable source", "acquisition status", "출처 후보", "자료 후보"),
    )
    return action and (source_kind or acquisition_noun or multiple_source_kinds)


def is_explicit_one_off_request(normalized_query: str, query_tokens: set[str]) -> bool:
    return bool(_ONE_OFF_TOKENS & query_tokens) or _contains_phrase(normalized_query, _ONE_OFF_PHRASES)


def _web_research_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _scheduled_ops_blueprint_guard_applies(normalized_query, query_tokens):
        return False
    if _delivery_cycle_terms(normalized_query, query_tokens):
        return False
    if {
        "web",
        "search",
        "sources",
        "source",
        "citation",
        "citations",
        "links",
        "latest",
        "current",
        "freshness",
        "official",
        "upstream",
    } & query_tokens:
        return True
    return _contains_phrase(
        normalized_query,
        (
            "web search",
            "search the web",
            "internet search",
            "find sources",
            "current sources",
            "source backed",
            "웹서치",
            "웹 서치",
            "웹 검색",
            "인터넷 검색",
            "검색해서",
            "검색해줘",
            "찾아봐",
            "최신 자료",
            "최신 출처",
            "자료 찾아",
        ),
    )


def _missed_workflow_research_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _scheduled_ops_blueprint_guard_applies(normalized_query, query_tokens):
        return False
    if _research_department_guard_applies(normalized_query, query_tokens):
        return False
    if not _missed_omh_workflow_context_applies(normalized_query):
        return False
    return bool(_MISSED_WORKFLOW_RESEARCH_TOKENS & query_tokens) or _contains_phrase(
        normalized_query, ("리서치", "조사", "자료", "출처", "research")
    )


def _missed_workflow_operating_record_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _visual_summary_guard_applies(normalized_query, query_tokens):
        return False
    if not _missed_omh_workflow_context_applies(normalized_query):
        return False
    meeting_context = bool(_MISSED_WORKFLOW_OPERATING_RECORD_TOKENS & query_tokens) or _contains_phrase(
        normalized_query,
        ("회의록", "회의 요약", "meeting notes", "meeting minutes"),
    )
    if not meeting_context:
        return False
    file_package_context = bool(_MATERIALS_PACKAGE_FORMAT_TOKENS & query_tokens) or _contains_phrase(
        normalized_query,
        ("ppt", "pdf", "deck", "slides", "엑셀", "피디에프"),
    )
    return not file_package_context


def _delivery_cycle_terms(normalized_query: str, query_tokens: set[str]) -> bool:
    if {
        "implement",
        "implementation",
        "code",
        "coding",
        "review",
        "docs",
        "documentation",
        "pull",
        "merge",
        "구현",
        "리뷰",
        "문서",
    } & query_tokens:
        return True
    return _contains_phrase(
        normalized_query,
        (
            "open a pr",
            "prepare a pr",
            "make a pr",
            "pr ready",
            "pr-ready",
            "pull request",
            "pr까지",
        ),
    )


def _coding_handoff_status_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _visual_summary_guard_applies(normalized_query, query_tokens):
        return False
    if _coding_session_status_only_guard_applies(normalized_query, query_tokens):
        return False
    explicit_phrase = _contains_phrase(normalized_query, _CODING_HANDOFF_PHRASES)
    executor = bool(_CODING_HANDOFF_EXECUTOR_TOKENS & query_tokens) or _contains_phrase(
        normalized_query,
        ("claude code", "coding agent", "코딩 에이전트"),
    )
    work = bool(_CODING_HANDOFF_WORK_TOKENS & query_tokens)
    control = bool(_CODING_HANDOFF_CONTROL_TOKENS & query_tokens)
    return explicit_phrase or (executor and work and control)


def _github_event_ops_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _contains_phrase(normalized_query, _GITHUB_EVENT_OPS_PHRASES):
        return True
    github_context = _contains_phrase(normalized_query, ("github", "깃허브"))
    issue_or_pr = bool(_GITHUB_EVENT_OPS_TOKENS & query_tokens) or _contains_phrase(
        normalized_query,
        ("issue", "pull request", "pr", "이슈"),
    )
    event_or_pr_prep = _contains_phrase(
        normalized_query,
        ("opened", "failed ci", "ci failed", "failing ci", "ci failing", "label", "review", "to pr", "into a pr", "pr 만들", "pr로", "들어온"),
    )
    event_context = _contains_phrase(normalized_query, ("opened", "failed ci", "ci failed", "failing ci", "ci failing", "label", "들어온"))
    return issue_or_pr and event_or_pr_prep and (github_context or event_context)


def _materials_package_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _visual_summary_guard_applies(normalized_query, query_tokens):
        return False
    if _contains_phrase(normalized_query, ("report package", "leadership status deck", "monthly leadership status")):
        return False
    if _contains_phrase(normalized_query, _MATERIALS_PACKAGE_PHRASES):
        return True
    format_hits = len(_MATERIALS_PACKAGE_FORMAT_TOKENS & query_tokens)
    action = bool(_MATERIALS_PACKAGE_ACTION_TOKENS & query_tokens) or _contains_phrase(
        normalized_query,
        ("make", "turn into", "prepare", "export", "만들", "정리", "준비", "공유"),
    )
    return format_hits >= 2 and action


def _memory_curation_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _contains_phrase(normalized_query, _MEMORY_CURATION_PHRASES):
        return True
    context = bool(_MEMORY_CURATION_CONTEXT_TOKENS & query_tokens)
    hermes_context = _contains_phrase(normalized_query, ("hermes", "헤르메스"))
    omh_context = _contains_phrase(normalized_query, ("omh", "oh-my-hermes", "oh my hermes"))
    cleanup = _contains_phrase(normalized_query, ("cleanup", "curate", "review", "inspect", "정리", "점검", "검토", "관리"))
    stale = _contains_phrase(normalized_query, ("stale", "old", "duplicate", "conflicting", "overlap", "collision", "오래된", "중복", "충돌", "겹", "압축"))
    capability_intent = bool(_CAPABILITY_INTENT_TOKENS & query_tokens)
    return context and (hermes_context or omh_context or stale or capability_intent) and cleanup


def _agent_board_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _contains_phrase(normalized_query, _AGENT_BOARD_PHRASES):
        return True
    multi_agent = _contains_phrase(
        normalized_query,
        ("multiple agents", "multi agent", "multiple hermes", "여러 에이전트", "여러 명", "agent 여러"),
    )
    board_or_roles = bool({"board", "kanban", "role", "roles", "보드", "역할", "칸반"} & query_tokens)
    team_context = bool(_AGENT_BOARD_CONTEXT_TOKENS & query_tokens)
    coordination = bool({"coordinate", "assign", "handoff", "route", "조율", "배정", "분배"} & query_tokens)
    named_roles = len({"pm", "cto", "qa", "security", "ops", "release"} & query_tokens) >= 2
    agents = bool({"agent", "agents", "에이전트"} & query_tokens)
    return (team_context and multi_agent and board_or_roles) or (coordination and agents and named_roles)


def _coding_progress_status_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _coding_session_status_only_guard_applies(normalized_query, query_tokens):
        return True
    if _contains_phrase(normalized_query, _CODING_PROGRESS_STATUS_PHRASES):
        return True
    executor = _contains_phrase(
        normalized_query,
        ("codex", "claude code", "coding agent", "executor", "코덱스", "클로드", "코딩 에이전트"),
    )
    progress = bool(_CODING_PROGRESS_STATUS_TOKENS & query_tokens) and _contains_phrase(
        normalized_query,
        ("progress", "status", "running", "where", "어디까지", "진행", "상태"),
    )
    return executor and progress


def _coding_session_status_only_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    executor = _contains_phrase(
        normalized_query,
        ("codex", "claude code", "coding agent", "executor", "코덱스", "클로드", "코딩 에이전트"),
    )
    return executor and _contains_phrase(normalized_query, _CODING_SESSION_STATUS_ONLY_PHRASES)


def _release_claim_review_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _reliability_review_context_applies(normalized_query, query_tokens):
        return False
    if _contains_phrase(normalized_query, _RELEASE_CLAIM_REVIEW_PHRASES):
        return True
    review_intent = bool(_RELEASE_CLAIM_REVIEW_TOKENS & query_tokens)
    claim_or_release = _contains_phrase(
        normalized_query,
        ("claim", "readme", "release", "doctor", "harness", "주장", "릴리즈"),
    )
    compare_or_verify = _contains_phrase(normalized_query, ("match", "matches", "verify", "review", "맞는지", "검토", "통과"))
    return review_intent and claim_or_release and compare_or_verify


def _doctor_health_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    code_change_context = {"implementation", "router"} & query_tokens and {
        "fix",
        "code",
        "change",
        "수정",
        "구현",
    } & query_tokens
    if code_change_context:
        return False
    if _contains_phrase(
        normalized_query,
        (
            "after omh update",
            "omh update says setup",
            "setup is next",
            "skills still look stale",
            "skills look stale",
            "hermes skills still",
            "hermes cannot see the skills",
            "hermes can't see the skills",
            "cannot see the skills",
            "can't see the skills",
            "setup says done but hermes cannot see",
            "setup says done but hermes can't see",
            "install looks broken",
            "setup looks broken",
            "registration looks broken",
            "omh가 이상",
            "설치가 이상",
            "셋업이 이상",
            "스킬이 안 보여",
            "스킬이 stale",
        ),
    ):
        return True
    omh_context = _contains_phrase(normalized_query, ("omh", "oh-my-hermes", "oh my hermes", "hermes skills"))
    maintenance = bool(
        {
            "install",
            "setup",
            "update",
            "doctor",
            "health",
            "registration",
            "stale",
            "skills",
            "path",
            "설치",
            "셋업",
            "업데이트",
            "닥터",
            "스킬",
            "등록",
            "상태",
        }
        & query_tokens
    )
    confusion = _contains_phrase(
        normalized_query,
        (
            "still",
            "stale",
            "missing",
            "not found",
            "broken",
            "doesn't work",
            "not working",
            "says setup",
            "look stale",
            "looks stale",
            "안 보여",
            "안됨",
            "안 돼",
            "이상",
            "깨짐",
        ),
    )
    return omh_context and maintenance and confusion


def _reliability_review_context_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    reliability = bool({"reliability", "slo", "postmortem", "incident"} & query_tokens) or _contains_phrase(
        normalized_query,
        (
            "reliability review",
            "service reliability",
            "slo review",
            "incident review",
            "incident postmortem",
            "error budget",
        ),
    )
    review = bool({"review", "check", "검토"} & query_tokens)
    return reliability and review


def _executor_runtime_readiness_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _contains_phrase(normalized_query, _EXECUTOR_RUNTIME_READINESS_PHRASES):
        return True
    runtime_intent = bool(_EXECUTOR_RUNTIME_READINESS_TOKENS & query_tokens) or _contains_phrase(
        normalized_query,
        ("runtime", "executor", "handoff", "런타임", "실행", "위임", "넘길", "넘길지"),
    )
    named_executor = _contains_phrase(
        normalized_query,
        ("codex", "claude code", "coding agent", "omx", "omo", "omc", "코덱스", "클로드"),
    )
    selection = _contains_phrase(
        normalized_query,
        ("which", "choose", "compare", "vs", "중 어떤", "어떤", "골라", "선택", "정해", "할까", "넘길지"),
    )
    run_capability = _contains_phrase(
        normalized_query,
        (
            "can this task run",
            "can this run",
            "run in codex",
            "run in claude",
            "run with codex",
            "run with claude",
        ),
    )
    return runtime_intent and named_executor and (selection or run_capability)


def _voice_operator_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _contains_phrase(normalized_query, _VOICE_OPERATOR_PHRASES):
        return True
    if _VOICE_OPERATOR_TOKENS & query_tokens and _CAPABILITY_INTENT_TOKENS & query_tokens:
        return True
    if _VOICE_OPERATOR_TOKENS & query_tokens and _contains_phrase(
        normalized_query,
        ("from mobile", "on mobile", "from phone", "mobile request", "mobile note"),
    ):
        return True
    return bool(_VOICE_OPERATOR_TOKENS & query_tokens) and _contains_phrase(
        normalized_query,
        ("clarify", "summarize", "route", "safe", "confirm", "정리", "안전", "확인", "라우팅"),
    )


def _visual_summary_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _is_short_visual_summary_request(normalized_query):
        return True
    explicit_visual_phrase = _contains_phrase(normalized_query, _VISUAL_SUMMARY_PHRASES)
    if explicit_visual_phrase:
        return True
    if (
        _missed_omh_workflow_context_applies(normalized_query)
        and _VISUAL_SUMMARY_MODALITY_TOKENS & query_tokens
        and not _VISUAL_SUMMARY_NON_VISUAL_WORK_TOKENS & query_tokens
    ):
        return True
    if _VISUAL_SUMMARY_CARD_TOKENS & query_tokens and _VISUAL_SUMMARY_OUTPUT_CONTEXT_TOKENS & query_tokens:
        return True
    if _VISUAL_SUMMARY_NON_VISUAL_WORK_TOKENS & query_tokens:
        return False
    if _VISUAL_SUMMARY_MODALITY_TOKENS & query_tokens and _VISUAL_SUMMARY_CAPABILITY_TOKENS & query_tokens:
        return True
    if _VISUAL_SUMMARY_MODALITY_TOKENS & query_tokens and _VISUAL_SUMMARY_OUTPUT_CONTEXT_TOKENS & query_tokens:
        return True
    if _VISUAL_SUMMARY_OUTPUT_CONTEXT_TOKENS & query_tokens and _contains_phrase(
        normalized_query,
        ("summary image", "summary card", "briefing card", "announcement image", "요약 이미지", "요약 카드"),
    ):
        return True
    return False


def _is_short_visual_summary_request(normalized_query: str) -> bool:
    compact = normalized_query.strip(" \t\r\n.!?,;:()[]{}\"'`~。？！、，；：")
    return compact in _VISUAL_SUMMARY_SHORT_REQUEST_PHRASES


def _missed_omh_workflow_context_applies(normalized_query: str) -> bool:
    if _contains_phrase(normalized_query, _OMH_MISSED_WORKFLOW_PHRASES):
        return True
    return ("omh" in normalized_query or "oh-my-hermes" in normalized_query) and _contains_phrase(
        normalized_query, _MISSED_WORKFLOW_ACTION_PHRASES
    )


def _deliverable_package_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _visual_summary_guard_applies(normalized_query, query_tokens):
        return False
    if _deliverable_gateway_context_applies(normalized_query, query_tokens):
        return False
    explicit_phrase = _contains_phrase(normalized_query, _DELIVERABLE_PHRASES)
    if explicit_phrase:
        return True
    if _DELIVERABLE_STRONG_TOKENS & query_tokens and _DELIVERABLE_FILE_TOKENS & query_tokens:
        return True
    return False


def _deliverable_gateway_context_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    gateway_context = bool(_DELIVERABLE_GATEWAY_CONTEXT_TOKENS & query_tokens) or _contains_phrase(
        normalized_query, _DELIVERABLE_GATEWAY_CONTEXT_PHRASES
    )
    if not gateway_context:
        return False
    deliverable_file_context = bool(_DELIVERABLE_FILE_TOKENS & query_tokens) or _contains_phrase(
        normalized_query, ("generated pdf", "generated file", "file attachment", "attach file")
    )
    return not deliverable_file_context


def _delivery_cycle_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _visual_summary_guard_applies(normalized_query, query_tokens):
        return False
    return _delivery_cycle_terms(normalized_query, query_tokens) and _contains_phrase(
        normalized_query,
        (
            "prepare a pr",
            "open a pr",
            "make a pr",
            "pr-ready",
            "pr ready",
            "pull request",
            "plan implement review docs",
            "research plan implement",
            "계획 구현 리뷰 문서",
            "기획 구현 리뷰 문서",
            "pr까지",
        ),
    )


def _explicit_delivery_or_implementation_requested(normalized_query: str, query_tokens: set[str]) -> bool:
    if _delivery_cycle_terms(normalized_query, query_tokens):
        return True
    return _contains_phrase(
        normalized_query,
        (
            "write the code",
            "implement the fix",
            "fix the code",
            "open the pr",
            "merge the pr",
            "코드 작성",
            "수정 구현",
            "pr 열",
            "pr 머지",
        ),
    )


def _contains_phrase(normalized_query: str, phrases: tuple[str, ...] | frozenset[str]) -> bool:
    return any(normalized_phrase(phrase) in normalized_query for phrase in phrases)
