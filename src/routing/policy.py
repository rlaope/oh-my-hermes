from __future__ import annotations

from dataclasses import dataclass

from .localization import normalized_phrase, routing_tokens


ROUTE_ACTIONS = ("dispatch", "clarify", "fallback")
CONFIDENCE_LEVELS = ("low", "medium", "high")
EXPLICIT_INVOCATION_PREFIXES = ("$", "/", "./", "@")
_EXPLICIT_SKILL_ALIASES = {
    "ohmy": "oh-my-hermes",
}
_PREFIXED_SKILL_ALIASES = {
    "omh": "oh-my-hermes",
    "ohmy": "oh-my-hermes",
    "skills": "oh-my-hermes",
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
)
_VISUAL_SUMMARY_CARD_TOKENS = _normalized_token_set({"card", "poster", "one-pager", "카드", "포스터", "海报", "海報"})
_VISUAL_SUMMARY_CAPABILITY_TOKENS = _normalized_token_set(
    {
        "support",
        "supports",
        "feature",
        "features",
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
_VISUAL_SUMMARY_NON_VISUAL_WORK_TOKENS = _normalized_token_set(
    {
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
_WORKFLOW_LEARNING_PHRASES = (
    "learn from this workflow",
    "learn from this workflow run",
    "learn from this run",
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
    "stale project context",
    "old project context",
    "hermes remembers",
    "기억하고 있는",
    "기억하고 있는 프로젝트 맥락",
    "프로젝트 맥락이 오래된",
    "오래된 맥락",
    "오래된 기억",
    "맥락이 오래된",
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
        "정리",
    }
)
_AGENT_BOARD_PHRASES = (
    "agent board",
    "multi agent board",
    "multiple hermes agents",
    "multiple hermes profiles",
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
    "coding agent status",
    "where is codex",
    "codex 작업",
    "codex 작업이 어디까지",
    "코덱스 작업",
    "작업이 어디까지",
    "진행됐는지",
    "진행되었는지",
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
    "mobile command",
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
FEEDBACK_BEFORE_CODING_GUARD = RoutingGuardRule(
    id="feedback_before_coding",
    rule="Product feedback and bug reports should route through triage/investigation before coding handoff unless code work is explicit.",
    matched_label="guard:feedback_before_coding",
    preferred_skills=("feedback-triage",),
    score_boost=0,
    why="Product feedback and bug reports should get triage/investigation before coding handoff.",
    activation_status="cataloged",
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
WEB_RESEARCH_BEFORE_PROCESS_GUARD = RoutingGuardRule(
    id="web_research_before_process",
    rule="Plain web/source/current-evidence requests should route to web research before one-cycle delivery.",
    matched_label="guard:web_research_before_process",
    preferred_skills=("web-research",),
    score_boost=14,
    why="Matched guard/trigger metadata; web, source, or freshness requests should start with source-backed Hermes research.",
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
ROUTING_GUARD_RULES = (
    RISKY_REFACTOR_GUARD,
    FEEDBACK_BEFORE_CODING_GUARD,
    PRODUCT_SHAPING_GUARD,
    WORKFLOW_LEARNING_GUARD,
    RESEARCH_DEPARTMENT_GUARD,
    SCHEDULED_OPS_BLUEPRINT_GUARD,
    WEB_RESEARCH_BEFORE_PROCESS_GUARD,
    MISSED_WORKFLOW_WEB_RESEARCH_GUARD,
    MISSED_WORKFLOW_OPERATING_RHYTHM_GUARD,
    GITHUB_EVENT_OPS_GUARD,
    MATERIALS_PACKAGE_GUARD,
    MEMORY_CURATION_GUARD,
    AGENT_BOARD_GUARD,
    CODING_PROGRESS_STATUS_GUARD,
    RELEASE_CLAIM_REVIEW_GUARD,
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
    if _product_shaping_guard_applies(normalized_query, query_tokens):
        rules.append(PRODUCT_SHAPING_GUARD)
    if _workflow_learning_guard_applies(normalized_query, query_tokens):
        rules.append(WORKFLOW_LEARNING_GUARD)
    delivery_cycle_applies = _delivery_cycle_guard_applies(normalized_query, query_tokens)
    research_department_applies = (
        not delivery_cycle_applies and _research_department_guard_applies(normalized_query, query_tokens)
    )
    if research_department_applies:
        rules.append(RESEARCH_DEPARTMENT_GUARD)
    if (
        not delivery_cycle_applies
        and _scheduled_ops_blueprint_guard_applies(normalized_query, query_tokens)
        and not research_department_applies
    ):
        rules.append(SCHEDULED_OPS_BLUEPRINT_GUARD)
    if _missed_workflow_operating_record_guard_applies(normalized_query, query_tokens):
        rules.append(MISSED_WORKFLOW_OPERATING_RHYTHM_GUARD)
    if _web_research_guard_applies(normalized_query, query_tokens):
        rules.append(WEB_RESEARCH_BEFORE_PROCESS_GUARD)
    if _missed_workflow_research_guard_applies(normalized_query, query_tokens):
        rules.append(MISSED_WORKFLOW_WEB_RESEARCH_GUARD)
    if _github_event_ops_guard_applies(normalized_query, query_tokens):
        rules.append(GITHUB_EVENT_OPS_GUARD)
    if _materials_package_guard_applies(normalized_query, query_tokens):
        rules.append(MATERIALS_PACKAGE_GUARD)
    if _memory_curation_guard_applies(normalized_query, query_tokens):
        rules.append(MEMORY_CURATION_GUARD)
    if _agent_board_guard_applies(normalized_query, query_tokens):
        rules.append(AGENT_BOARD_GUARD)
    if _coding_progress_status_guard_applies(normalized_query, query_tokens):
        rules.append(CODING_PROGRESS_STATUS_GUARD)
    if _release_claim_review_guard_applies(normalized_query, query_tokens):
        rules.append(RELEASE_CLAIM_REVIEW_GUARD)
    if _executor_runtime_readiness_guard_applies(normalized_query, query_tokens):
        rules.append(EXECUTOR_RUNTIME_READINESS_GUARD)
    if _voice_operator_guard_applies(normalized_query, query_tokens):
        rules.append(VOICE_OPERATOR_GUARD)
    if _visual_summary_guard_applies(normalized_query, query_tokens):
        rules.append(VISUAL_SUMMARY_GUARD)
    if _deliverable_package_guard_applies(normalized_query, query_tokens):
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


def _workflow_learning_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _contains_phrase(normalized_query, _WORKFLOW_LEARNING_PHRASES):
        return True
    learning = bool({"learn", "learning", "학습"} & query_tokens)
    workflow_or_skill = bool({"workflow", "run", "trace", "skill", "routing", "route", "워크플로우", "스킬", "라우팅"} & query_tokens)
    future_improvement = bool({"improve", "improvement", "next", "future", "regression", "개선", "회귀"} & query_tokens)
    if learning and workflow_or_skill:
        return True
    if future_improvement and workflow_or_skill and bool(_WORKFLOW_LEARNING_CONTEXT_TOKENS & query_tokens):
        return True
    return False


def _scheduled_ops_blueprint_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if is_explicit_one_off_request(normalized_query, query_tokens):
        return False
    if _SCHEDULED_OPS_STRONG_TOKENS & query_tokens:
        return True
    if _SCHEDULED_OPS_CADENCE_TOKENS & query_tokens and _SCHEDULED_OPS_CONTEXT_TOKENS & query_tokens:
        return True
    return _contains_phrase(normalized_query, _SCHEDULED_OPS_PHRASES)


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
        ("opened", "failed ci", "ci failed", "label", "review", "to pr", "into a pr", "pr 만들", "pr로", "들어온"),
    )
    event_context = _contains_phrase(normalized_query, ("opened", "failed ci", "ci failed", "label", "들어온"))
    return issue_or_pr and event_or_pr_prep and (github_context or event_context)


def _materials_package_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _visual_summary_guard_applies(normalized_query, query_tokens):
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
    cleanup = _contains_phrase(normalized_query, ("cleanup", "curate", "review", "inspect", "정리", "점검", "검토"))
    stale = _contains_phrase(normalized_query, ("stale", "old", "duplicate", "conflicting", "오래된", "중복", "충돌"))
    return context and (hermes_context or stale) and cleanup


def _agent_board_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _contains_phrase(normalized_query, _AGENT_BOARD_PHRASES):
        return True
    multi_agent = _contains_phrase(
        normalized_query,
        ("multiple agents", "multi agent", "multiple hermes", "여러 에이전트", "여러 명", "agent 여러"),
    )
    board_or_roles = bool({"board", "kanban", "role", "roles", "보드", "역할", "칸반"} & query_tokens)
    team_context = bool(_AGENT_BOARD_CONTEXT_TOKENS & query_tokens)
    return team_context and multi_agent and board_or_roles


def _coding_progress_status_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
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


def _release_claim_review_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _contains_phrase(normalized_query, _RELEASE_CLAIM_REVIEW_PHRASES):
        return True
    review_intent = bool(_RELEASE_CLAIM_REVIEW_TOKENS & query_tokens)
    claim_or_release = _contains_phrase(
        normalized_query,
        ("claim", "readme", "release", "doctor", "harness", "주장", "릴리즈"),
    )
    compare_or_verify = _contains_phrase(normalized_query, ("match", "matches", "verify", "review", "맞는지", "검토", "통과"))
    return review_intent and claim_or_release and compare_or_verify


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
    return runtime_intent and named_executor and selection


def _voice_operator_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
    if _contains_phrase(normalized_query, _VOICE_OPERATOR_PHRASES):
        return True
    return bool(_VOICE_OPERATOR_TOKENS & query_tokens) and _contains_phrase(
        normalized_query,
        ("clarify", "summarize", "route", "safe", "confirm", "정리", "안전", "확인", "라우팅"),
    )


def _visual_summary_guard_applies(normalized_query: str, query_tokens: set[str]) -> bool:
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


def _contains_phrase(normalized_query: str, phrases: tuple[str, ...] | frozenset[str]) -> bool:
    return any(normalized_phrase(phrase) in normalized_query for phrase in phrases)
