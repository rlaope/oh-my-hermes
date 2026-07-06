from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import re
import unicodedata
from typing import Any

from ..goal_loop import explicit_loop_invocation_signal
from ..ingress import CHAT_SOURCES, extract_message_text
from ..loopability import assess_loopability
from .catalog_questions import (
    is_catalog_without_shell_question,
    is_file_or_text_lookup_question,
    is_native_entrypoint_question,
    is_skill_catalog_question,
)
from .action_copy import next_action_label as _route_next_action_label
from .intent import scrub_diagnostic_status_text
from .localization import normalized_phrase, prepare_routing_text, routing_tokens
from .missed_route import is_missed_route_feedback
from .omh_help import is_omh_intro_question, is_omh_quickstart_question, is_omh_status_question
from .policy import (
    CONFIDENCE_LEVELS,
    ROUTE_ACTIONS,
    active_routing_guard_rules,
    explicit_skill_invocation as explicit_skill_name,
    is_ambiguous_scores,
    meets_confidence_threshold,
)
from .recommend import recommendation_for_definition, recommend_skills
from .route_plan import build_workflow_route_plan, compact_workflow_route_plan
from .task_cards import classify_task, task_card_recommendation
from .visual_qa_cues import (
    BROWSER_VISUAL_QA_COMMAND_PHRASES,
    BROWSER_VISUAL_QA_PHRASES,
    CUSTOMER_SYMPTOM_REPORT_PHRASES,
    contains_cue_phrase,
)
from ..learning_candidate import build_learning_candidate_card
from ..surfaces.evidence_copy import not_evidence_action_suffix, not_evidence_reply_suffix
from ..skills.catalog import SkillDefinition, primary_harness_for_skill, routable_definitions


FILE_LOOKUP_REASON = (
    "File or text lookup request; answer directly or ask for the target file instead of dispatching to a workflow keyword."
)
DIRECT_ANSWER_REASON = (
    "Plain user question; answer directly in chat instead of opening an OMH workflow or picker."
)
ROUTE_EXPLANATION_SCHEMA_VERSION = "route_explanation/v1"
_ROUTER_SKILL = "oh-my-hermes"
_SPECIFIC_CAPABILITY_CATALOG_MIN_SCORE = 6
_SPECIFIC_CAPABILITY_EXCLUDED_SKILLS = frozenset(
    {
        _ROUTER_SKILL,
        "ask",
        "cancel",
        "plan",
        "skill",
        "team",
    }
)
_BROAD_CAPABILITY_CATALOG_PHRASES = (
    "planning, research, and coding",
    "planning/research/coding",
    "planning, research, coding",
    "deep-interview/ralplan/loop",
    "계획/리서치/코딩",
    "플랜/리서치/코딩",
)
_BROAD_CAPABILITY_TOPIC_TOKENS = frozenset(
    {
        "planning",
        "plan",
        "research",
        "coding",
        "interview",
        "workflow",
        "workflows",
        "skill",
        "skills",
        "계획",
        "플랜",
        "리서치",
        "코딩",
        "워크플로",
        "워크플로우",
        "스킬",
    }
)
_DIRECT_PICKER_ALIASES = frozenset(("./", "./o", "./om", "./omh", "/o", "/om", "/omh", "./skills", "/skills"))
_DIRECT_MAINTENANCE_LIST_COMMANDS = frozenset(
    (
        "omh list",
        "./omh list",
        "/omh list",
        "oh my hermes list",
        "oh-my-hermes list",
        "omh 목록",
        "./omh 목록",
        "/omh 목록",
        "omh 리스트",
        "./omh 리스트",
        "/omh 리스트",
    )
)
_GUARDED_OPERATOR_FAST_PATH_IDS = frozenset(
    {
        "coding_handoff_status_before_clarify",
        "coding_progress_status_before_clarify",
        "doctor_health_before_skill_catalog",
        "executor_runtime_readiness_before_generic_advice",
        "harness_session_inventory_before_toolbelt_or_observability",
        "img_summary_before_materials_or_delivery",
        "memory_curation_before_generic_clarification",
        "ops_observability_before_generic_loop",
        "toolbelt_readiness_before_generic_or_visual_fallback",
        "workspace_file_operator_before_materials_or_coding",
        "command_operator_before_generic_terminal_or_coding",
    }
)
_GUARDED_OPERATOR_FAST_PATH_PRIORITY = (
    "executor_runtime_readiness_before_generic_advice",
    "harness_session_inventory_before_toolbelt_or_observability",
    "coding_handoff_status_before_clarify",
    "coding_progress_status_before_clarify",
    "ops_observability_before_generic_loop",
    "doctor_health_before_skill_catalog",
    "toolbelt_readiness_before_generic_or_visual_fallback",
    "workspace_file_operator_before_materials_or_coding",
    "command_operator_before_generic_terminal_or_coding",
    "img_summary_before_materials_or_delivery",
    "memory_curation_before_generic_clarification",
)
_GUARDED_OPERATOR_META_BLOCKERS = (
    "developer note",
    "developer test",
    "not asking to",
    "only vocabulary",
    "vocabulary",
    "route:",
    "routing",
    "router",
    "setup test",
    "test:",
    "라우팅",
    "라우터",
    "용어",
    "오해",
    "테스트",
    "요구사항은 없어",
)
_FEEDBACK_TRIAGE_FAST_PATH_BLOCKERS = (
    "codex",
    "claude code",
    "handoff",
    "implementation",
    "implement",
    "fix",
    "review",
    "track",
    "repro",
    "reproduction",
    "plan",
    "pr",
    *BROWSER_VISUAL_QA_PHRASES,
    "코덱스",
    "클로드 코드",
    "핸드오프",
    "구현",
    "고쳐",
    "고치",
    "수정",
    "리뷰",
    "추적",
    "재현",
    "계획",
    "pr",
)
_BROWSER_VISUAL_QA_FAST_PATH_TERMS = BROWSER_VISUAL_QA_COMMAND_PHRASES
_CUSTOMER_SYMPTOM_REPORT_FAST_PATH_TERMS = CUSTOMER_SYMPTOM_REPORT_PHRASES
_FEEDBACK_TRIAGE_FAST_PATH_TERMS = (
    "payment failure",
    "payment failures",
    "checkout is broken",
    "checkout broken",
    "checkout timeout",
    "checkout timeouts",
    "refunds after checkout",
    "app keeps crashing",
    "crashing after login",
    "dashboard 500",
    "dashboard 500s",
    "login 500",
    "결제 실패",
    "결제실패",
    "체크아웃 실패",
    "체크아웃 오류",
    "로그인 후 크래시",
    "로그인하고 크래시",
    "대시보드 500",
)
_PRODUCT_SHAPING_FAST_PATH_BLOCKERS = _FEEDBACK_TRIAGE_FAST_PATH_BLOCKERS + (
    "bug",
    "issue",
    "broken",
    "create a pr",
    "open a pr",
    "pull request",
    "버그",
    "이슈",
    "pr 만들어",
    "pr 열어",
)
_PRODUCT_SHAPING_FAST_PATH_TERMS = (
    "improve our onboarding",
    "improve onboarding",
    "make onboarding smoother",
    "make onboarding feel smoother",
    "make the user experience smoother",
    "make the product experience better",
    "not sure where to start",
    "where to start",
    "온보딩을 더 부드럽게",
    "온보딩 개선",
    "어디서 시작",
    "어디부터 시작",
)
_LEARNING_CANDIDATE_FAST_PATH_BLOCKERS = (
    "learn this",
    "make a skill from this",
    "from now on",
    "기억해:",
    "기억해",
)
_WORKFLOW_LEARNING_FAST_PATH_TERMS = (
    "workflow trace",
    "workflow traces",
    "learning trace",
    "skill improvement",
    "skill patch",
    "routing regression",
    "regression case",
    "route regression",
    "workflow went wrong",
    "improve a workflow",
    "workflow learning",
    "omh 기능",
    "omh context",
    "omh 컨텍스트",
    "generic answer",
    "general answer",
    "일반 답변",
    "워크플로우",
    "워크플로",
    "스킬",
    "라우팅",
    "라우터",
)
_WORKFLOW_LEARNING_FAST_PATH_ACTION_TERMS = (
    "improve",
    "improvement",
    "fix next time",
    "next time",
    "learn from",
    "add regression",
    "record",
    "audit",
    "patch",
    "고칠",
    "개선",
    "다음엔",
    "다음에는",
    "학습",
    "기록",
    "회귀",
    "틀렸",
    "안 썼",
    "안쓴",
    "모르",
    "못 보",
    "빠져",
    "빠짐",
    "잘못 고른",
    "잘못 골",
)
_BOUNDARY_MARKER_LABELS: tuple[tuple[str, str], ...] = (
    ("meeting happened", "meeting occurrence"),
    ("meeting, scrum, sprint, retro", "meeting/scrum/sprint/retro occurrence"),
    ("scrum, sprint, retro", "meeting/scrum/sprint/retro occurrence"),
    ("decisions were accepted", "decision acceptance"),
    ("decision, or action item", "decision acceptance"),
    ("action item happened", "action item completion"),
    ("not deploy", "deployment"),
    ("health-check", "health check"),
    ("health check", "health check"),
    ("rollback", "rollback"),
    ("incident evidence", "incident evidence"),
    ("target accepted", "target acceptance"),
    ("agent accepted", "target acceptance"),
    ("accepted, worked", "target acceptance"),
    ("accepted, executed", "target acceptance"),
    ("worked", "work progress"),
    ("executed, heartbeat", "work progress"),
    ("heartbeat-ed", "heartbeat"),
    ("heartbeat", "heartbeat"),
    ("completed work", "completion"),
    ("or completed.", "completion"),
    ("billing truth", "billing truth"),
    ("provider quota truth", "provider quota truth"),
    ("complete tracing", "complete tracing"),
    ("workflow completion", "workflow completion"),
    ("successful workflow completion", "workflow completion"),
    ("host load", "host load"),
    ("mcp tool-call", "MCP tool-call"),
    ("mcp tool call", "MCP tool-call"),
    ("connector availability", "connector availability"),
    ("worktree cleanup", "worktree cleanup"),
    ("merge-conflict resolution", "merge-conflict resolution"),
    ("merge conflict resolution", "merge-conflict resolution"),
    ("session progress", "session progress"),
    ("command execution", "command execution"),
    ("artifact write", "artifact write"),
    ("runtime, tool, mcp server", "runtime proof"),
    ("tool, mcp server, ci job", "tool invocation"),
    ("mcp server, ci job", "MCP server"),
    ("platform action", "platform action"),
    ("performance proof", "performance proof"),
    ("full pdf extraction", "full PDF extraction"),
    ("figure ocr", "figure OCR"),
    ("external citation checking", "external citation checking"),
    ("citation checking", "external citation checking"),
    ("math validation", "math validation"),
    ("code reproduction", "code reproduction"),
    ("paper claims", "paper claim verification"),
    ("generated image", "image generation"),
    ("image generation", "image generation"),
    ("visual qa", "visual QA"),
    ("file export", "file export"),
    ("file generation", "file generation/export"),
    ("file extraction", "file extraction"),
    ("web search", "web search"),
    ("source retrieval", "source retrieval"),
    ("sources were fetched", "source retrieval"),
    ("repository clone", "repository clone"),
    ("download", "download"),
    ("file hash verification", "file hash verification"),
    ("license verification", "license verification"),
    ("source correctness verification", "source correctness verification"),
)
_BOUNDARY_REGEX_LABELS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern), label)
    for pattern, label in (
        (r"\bplan acceptance\b", "plan acceptance"),
        (r"\bdispatch(?:ed)?\b", "executor/runtime dispatch"),
        (r"\bexecution\b", "execution"),
        (r"\bimplementation\b", "implementation"),
        (r"\bapi\b", "API access"),
        (r"\bcredential\b", "credential validation"),
        (r"\bconnector\b", "connector invocation"),
        (r"\bdelivery\b", "delivery"),
        (r"\battachment\b", "attachment"),
        (r"\breview\b", "review"),
        (r"\bverification\b", "verification"),
        (r"\bci\b", "CI"),
        (r"\bmerge(?:-readiness)?\b", "merge"),
    )
)
_GENERIC_CATALOG_COLLECTION_MARKERS = (
    "workflow",
    "workflows",
    "skill",
    "skills",
    "command",
    "commands",
    "기능",
    "명령",
    "스킬",
    "워크플로",
    "워크플로우",
)
_GENERIC_PICKER_COLLECTION_MARKERS = tuple(
    marker for marker in _GENERIC_CATALOG_COLLECTION_MARKERS if marker != "기능"
)
_GENERIC_CATALOG_LISTING_MARKERS = (
    "available",
    "installed",
    "do you have",
    "can omh do",
    "can oh-my-hermes do",
    "explain",
    "describe",
    "list",
    "show",
    "menu",
    "picker",
    "알려",
    "보여",
    "뭐있어",
    "뭐 있어",
    "뭐가있어",
    "뭐가 있어",
    "무엇이 있어",
    "목록",
    "리스트",
    "할 수 있는",
)
_GENERIC_OMH_CAPABILITY_LISTING_MARKERS = (
    "what can omh do",
    "what can oh-my-hermes do",
    "what does omh do",
    "what does oh-my-hermes do",
    "how can omh help",
    "how can oh-my-hermes help",
    "omh 뭐 할 수",
    "omh 무엇을 할 수",
    "omh에서 쓸 수 있는",
    "omh가 뭐 해",
    "omh가 무엇을 해",
    "omh는 뭐 해",
    "omh는 무엇을 해",
    "omh 기능 뭐",
)
_SPECIFIC_CAPABILITY_ALIAS_PHRASES = (
    "workflow learning",
    "workflow trace",
    "skill patch",
    "routing regression",
    "route regression",
    "research ops",
    "gateway routing",
    "message routing",
    "platform routing",
    "coding agents",
    "coding agent",
    "executors",
    "runtimes",
)
_SPECIFIC_CAPABILITY_FAST_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "paper-learning",
        (
            "papers",
            "paper pdf",
            "paper pdfs",
            "pdf papers",
            "paper explanation",
            "paper learning",
        ),
    ),
    (
        "source-finder",
        (
            "source finding",
            "source acquisition",
            "source candidates",
            "datasets",
            "dataset search",
            "github repos",
            "github repositories",
            "github oss repos",
            "public presentations",
        ),
    ),
    (
        "workflow-learning",
        (
            "workflow learning",
            "learning trace",
            "skill patch",
            "routing regression",
        ),
    ),
    (
        "instinct-ledger",
        (
            "instinct ledger",
            "project instincts",
            "project-scoped instincts",
            "global instincts",
            "instinct promotion",
            "export instincts",
        ),
    ),
    (
        "agent-debug",
        (
            "agent debug",
            "agent debugging",
            "agent introspection",
            "agent self-debug",
            "self-debug",
            "self debugging",
            "looping agent",
            "agent loop failure",
            "agent run stuck",
            "tool retry loop",
            "repeated tool calls",
            "agent context drift",
        ),
    ),
    (
        "skill-scout",
        (
            "skill scout",
            "skill scouting",
            "skill candidate",
            "skill candidates",
            "skill candidate search",
            "skill discovery",
            "find a skill",
            "find skills",
            "existing skill",
            "fork a skill",
            "extend a skill",
        ),
    ),
    (
        "skill-health",
        (
            "skill health",
            "skill health dashboard",
            "skill health dashboards",
            "skill portfolio health",
            "skill dashboard",
            "skill dashboards",
            "pending skill amendments",
        ),
    ),
    (
        "gateway-intent-card",
        (
            "discord gateway routing",
            "gateway routing",
            "message routing",
            "platform routing",
        ),
    ),
    (
        "executor-runtime-readiness",
        (
            "coding agents",
            "coding agent",
            "executors",
            "runtimes",
        ),
    ),
    (
        "img-summary",
        (
            "image generation",
            "image generation features",
            "image generation support",
            "image tool support",
            "visual generation",
            "visual card support",
            "summary image",
            "image cards",
        ),
    ),
)
_DIRECT_ANSWER_STARTERS = (
    "what ",
    "what's ",
    "whats ",
    "how ",
    "how do ",
    "how can ",
    "why ",
    "please explain",
    "explain ",
    "describe ",
    "tell me ",
)
_DIRECT_ANSWER_SOFT_PREFIXES = (
    "just ",
    "can you ",
    "could you ",
)
_DIRECT_ANSWER_HOW_TO_STARTERS = (
    "how ",
    "how do ",
    "how do i ",
    "how can ",
    "how can i ",
    "how to ",
)
_DIRECT_ANSWER_CONCEPT_STARTERS = (
    "what is ",
    "what's ",
    "whats ",
    "what are ",
    "what does ",
    "define ",
    "meaning of ",
    "explain what ",
    "explain the concept of ",
)
_DIRECT_ANSWER_MULTILINGUAL_CONCEPT_STARTERS = (
    "¿qué es ",
    "qué es ",
    "que es ",
    "qu'est-ce que ",
    "qu’est-ce que ",
    "was ist ",
)
_DIRECT_ANSWER_CONCEPT_EXPLAIN_STARTERS = (
    "explain ",
    "describe ",
    "tell me about ",
)
_DIRECT_ANSWER_MULTILINGUAL_EXPLAIN_STARTERS = (
    "explícame ",
    "explicame ",
    "explique ",
    "erkläre ",
    "erklaere ",
)
_DIRECT_ANSWER_MULTILINGUAL_CONCEPT_MARKERS = (
    "とは何ですか",
    "とはなんですか",
    "とは何",
    "是什么",
    "是什麼",
    "क्या है",
    "क्या हैं",
    "क्या होता है",
)
_DIRECT_ANSWER_MULTILINGUAL_EXPLAIN_MARKERS = (
    "説明して",
    "説明してください",
    "解释一下",
    "解釋一下",
)
_DIRECT_ANSWER_MULTILINGUAL_CONTEXT_QUESTIONS = (
    "was ist los",
)
_AGENT_OPS_STATUS_FAST_PATH_SKILL = "agent-ops-review"
_AGENT_OPS_STATUS_FAST_PATH_EXACT_PHRASES = (
    "status update please",
    "give me a status update",
    "show me the current status",
    "what is the current status",
    "what are you doing",
    "what are you doing now",
    "what is going on",
    "what is going on rn",
    "what are you working on",
    "what was i working on",
    "what is the current pr status",
    "what is current pr status",
    "current pr status",
    "pr status update",
    "current pr review status",
    "did the current pr review pass",
    "is the current work done",
    "is this work done",
    "show session status",
    "show me the session status",
    "where are we",
    "where are we at",
    "start the omh menubar",
    "restart the omh menubar",
    "start the omh menu bar",
    "restart the omh menu bar",
    "start omh hud",
    "restart omh hud",
    "show the omh menu bar",
    "show the omh menubar",
    "omh menu bar icon is missing",
    "omh menubar icon is missing",
    "did ci pass",
    "ci passed",
    "ci status",
    "did the pr merge",
    "is the pr merged",
    "is this ready to ship",
    "is this ready to release",
    "qué está pasando",
    "que esta pasando",
    "qu'est-ce qui se passe",
    "was ist los",
    "今何してる",
    "现在在做什么",
)
_AGENT_OPS_STATUS_FAST_PATH_COMPACT_PHRASES = (
    "무슨일이야",
    "무슨일있었어",
    "무슨일이노",
    "뭔일임",
    "뭐해",
    "뭐함",
    "지금뭐함",
    "뭐하고있어",
    "뭐하는중이야",
    "요즘뭐하는중",
    "지금뭐해",
    "지금뭐하는중이야",
    "지금뭐하고있어",
    "작업상황브리핑해줘",
    "작업상황보고해줘",
    "작업상황알려줘",
    "현재작업상황브리핑해줘",
    "현재작업상황보고해줘",
    "현재작업상황알려줘",
    "진행상황알려줘",
    "진행중인거뭐야",
    "지금진행중인작업알려줘",
    "지금진행중인작업뭐야",
    "현재상태알려줘",
    "현재상태브리핑해줘",
    "현재작업뭐야",
    "이번작업끝났는지확인해줘",
    "이번작업끝났어",
    "이번작업완료됐어",
    "현재세션상태",
    "세션상태보여줘",
    "pr상태알려줘",
    "현재pr상태",
    "현재pr리뷰통과했어",
    "현재pr리뷰상태",
    "pr머지됐는지확인해줘",
    "pr머지됐어",
    "pr머지되었어",
    "ci통과했어",
    "ci통과했는지확인해줘",
    "ci상태알려줘",
    "기능배포준비됐어",
    "이기능배포준비됐어",
    "기능배포준비됐는지확인해줘",
    "이기능배포준비됐는지확인해줘",
    "배포준비됐어",
    "배포준비됐는지확인해줘",
    "릴리즈준비됐어",
    "pr진행상황",
    "pr어디까지됐어",
    "내가뭘하고있었는지알려줘",
    "뭘하고있었는지알려줘",
    "현재진행상황",
    "지금상황어때",
    "어디까지했노",
    "어디까지됐노",
    "어디까지됐어",
    "어디까지됨",
    "상단바hud다시켜고싶어",
    "상단바hud다시키고싶어",
    "상단바omh아이콘안보여",
    "상단바아이콘안보여",
    "메뉴바모니터다시켜줘",
    "메뉴바모니터다시키고싶어",
    "메뉴바모니터링다시띄워줘",
    "메뉴바다시켜줘",
    "메뉴바다시키고싶어",
)
_DIRECT_ANSWER_KOREAN_CONCEPT_MARKERS = (
    "뭐야",
    "무엇",
    "무슨 뜻",
    "뜻이 뭐",
)
_DIRECT_ANSWER_KOREAN_EXPLAIN_MARKERS = (
    "설명해",
    "설명해줘",
    "설명해 줘",
)
_DIRECT_ANSWER_CONCEPT_KEYWORDS = (
    "agent",
    "api",
    "error",
    "handoff",
    "image summary",
    "llm",
    "loop",
    "mcp",
    "memory leak",
    "oauth",
    "paper abstract",
    "pattern",
    "python",
    "release note",
    "research brief",
    "source control",
    "stack trace",
    "strategy",
    "triage",
    "venv",
    "virtualenv",
    "virtual environment",
    "workflow",
)
_DIRECT_ANSWER_ACKNOWLEDGEMENTS = (
    "thanks",
    "thank you",
    "thx",
    "ok",
    "okay",
    "got it",
    "gracias",
    "merci",
    "danke",
    "ありがとう",
    "谢谢",
    "謝謝",
    "धन्यवाद",
    "शुक्रिया",
    "고마워",
    "감사합니다",
    "감사",
    "ㅇㅋ",
    "오케이",
    "좋아",
)
_DIRECT_ANSWER_CONTEXT_QUESTIONS = (
    "what happened?",
    "what happened",
    "what should i do next?",
    "what should i do next",
    "what did i just ask?",
    "what did i just ask",
    "how should i proceed?",
    "how should i proceed",
    "무슨 일이야?",
    "무슨 일이야",
    "다음은 뭐야?",
    "다음은 뭐야",
    "내가 방금 뭐라고 했지?",
    "내가 방금 뭐라고 했지",
    "어떻게 해야 해?",
    "어떻게 해야 해",
)
_DIRECT_ANSWER_ERROR_HELP_STARTERS = (
    "command not found",
    "comando no encontrado",
    "commande introuvable",
    "befehl nicht gefunden",
    "permission denied",
    "modulenotfounderror",
    "module not found",
    "look at this log",
    "explain this log",
    "explain this stack trace",
    "please explain this stack trace",
    "why is this failing",
    "コマンドが見つかりません",
    "找不到命令",
)
_DIRECT_ANSWER_KOREAN_ERROR_HELP_SUBJECTS = (
    "이 오류",
    "이 에러",
    "이 로그",
    "이 스택트레이스",
)
_DIRECT_ANSWER_KOREAN_ERROR_HELP_ACTIONS = (
    "왜",
    "해결",
    "방법",
    "알려줘",
    "봐줘",
    "설명",
    "뭐임",
    "뭔데",
    "무슨",
    "뜻",
)
_DIRECT_ANSWER_ERROR_HELP_HARD_BLOCKERS = (
    "pr",
    "issue",
    "github",
    "ci",
    "repo",
    "repository",
    "codebase",
    "readme",
    "file",
    "files",
    "deploy",
    "release",
    "workflow",
    "workflows",
    "skill",
    "skills",
    "paper",
    "pdf",
    "image",
    "poster",
    "이슈",
    "레포",
    "저장소",
    "리드미",
    "파일",
    "배포",
    "릴리즈",
    "워크플로",
    "스킬",
    "논문",
    "이미지",
)
_DIRECT_ANSWER_CONCEPT_HARD_BLOCKERS = (
    "omh",
    "oh-my-hermes",
    "oh my hermes",
    "hermes",
    "codex",
    "claude",
    "repo",
    "repository",
    "codebase",
    "readme",
    "file",
    "files",
    "docs/",
    "src/",
    "tests/",
    "pr",
    "issue",
    "status",
    "current",
    "going on",
    "working on",
    "poster",
    "paper",
    "arxiv",
    "doi",
    "link",
    "summary card",
    "as image",
    "as an image",
    "into image",
    "into an image",
    "image card",
    "visual card",
    "pdf",
    "ppt",
    "implement",
    "build",
    "fix",
    "add",
    "create",
    "generate",
    "review",
    "deploy",
    "this paper",
    "this pdf",
    "this code",
    "attached paper",
    "attached pdf",
    "論文",
    "论文",
    "논문",
    "이 논문",
    "이 pdf",
    "이 코드",
    "첨부",
    "상태",
    "진행",
    "작업",
    "이슈",
    "레포",
    "저장소",
    "파일",
    "리드미",
    "이미지로",
    "사진으로",
    "카드로",
    "시각화해",
    "시각화해서",
    "헤르메스",
)
_DIRECT_ANSWER_BLOCKED_TERM_CONCEPTS = (
    "repo",
    "repository",
    "git repo",
    "git repository",
    "github repo",
    "github repository",
    "pr",
    "pull request",
    "github pr",
    "github pull request",
    "issue",
    "github issue",
)
_DIRECT_ANSWER_GENERIC_CONCEPT_MAX_WORDS = 8
_DIRECT_ANSWER_GENERIC_KOREAN_CONCEPT_MAX_CHARS = 48
_DIRECT_ANSWER_KEYWORDS = (
    "python",
    "list comprehension",
    "path",
    "zsh",
    "bash",
    "shell",
    "stack trace",
    "error",
    "means",
    "mean",
    "concept",
)
_DIRECT_ANSWER_SETUP_KEYWORDS = (
    "virtualenv",
    "virtual env",
    "virtual environment",
    "venv",
    "python environment",
    "pip install",
    "pipx",
    "path in zsh",
    "path in bash",
    "shell profile",
)
_DIRECT_ANSWER_HARD_BLOCKERS = (
    "omh",
    "oh-my-hermes",
    "oh my hermes",
    "hermes",
    "workflow",
    "workflows",
    "skill",
    "skills",
    "codex",
    "claude",
    "pr",
    "issue",
    "repo",
    "repository",
    "codebase",
    "research",
    "paper",
    "arxiv",
    "doi",
    "link",
    "pdf",
    "image",
    "poster",
    "summary card",
)
_DIRECT_ANSWER_TEXT_TRANSFORM_STARTERS = (
    "summarize this",
    "summarise this",
    "summarize this paragraph",
    "summarise this paragraph",
    "summarize the paragraph",
    "summarise the paragraph",
    "translate this",
    "traduce esto",
    "traduis ceci",
    "übersetze das",
    "uebersetze das",
    "translate this paragraph",
    "rewrite this paragraph",
    "rephrase this paragraph",
    "summarize this sentence",
    "summarise this sentence",
    "translate this sentence",
    "rewrite this",
    "rewrite this sentence",
    "rephrase this",
    "rephrase this sentence",
    "proofread this",
    "fix grammar in this",
    "make this more natural",
    "resume esto",
    "résume ceci",
    "fass das zusammen",
    "これを英語に翻訳して",
    "これを要約して",
    "把这句话翻译",
    "总结一下",
    "इसका सारांश",
    "इसे सारांश",
    "इसे अंग्रेज़ी में अनुवाद",
    "इसे अंग्रेजी में अनुवाद",
    "इसे हिंदी में अनुवाद",
)
_DIRECT_ANSWER_KOREAN_TEXT_TRANSFORM_SUBJECTS = (
    "이 문장",
    "이 문단",
    "이 글",
    "이 텍스트",
    "아래 문장",
    "아래 문단",
    "아래 글",
    "아래 텍스트",
)
_DIRECT_ANSWER_KOREAN_TEXT_TRANSFORM_ACTIONS = (
    "번역",
    "요약",
    "고쳐",
    "고쳐줘",
    "다듬",
    "자연스럽",
    "맞춤법",
    "문법",
    "교정",
)
_DIRECT_ANSWER_TEXT_TRANSFORM_HARD_BLOCKERS = (
    "omh",
    "oh-my-hermes",
    "oh my hermes",
    "hermes",
    "workflow",
    "workflows",
    "skill",
    "skills",
    "codex",
    "claude",
    "pr",
    "issue",
    "repo",
    "repository",
    "codebase",
    "readme",
    "file",
    "files",
    "docs/",
    "src/",
    "tests/",
    "research",
    "paper",
    "arxiv",
    "doi",
    "link",
    "pdf",
    "image",
    "poster",
    "summary card",
    "visual card",
    "meeting",
    "meeting notes",
    "transcript",
    "release",
    "이슈",
    "레포",
    "저장소",
    "리드미",
    "파일",
    "자료",
    "논문",
    "링크",
    "이미지",
    "사진",
    "카드",
    "회의",
    "회의록",
    "릴리즈",
    "헤르메스",
    "워크플로",
    "스킬",
)
_DIRECT_ANSWER_BLOCKERS = (
    "omh",
    "oh-my-hermes",
    "oh my hermes",
    "hermes",
    "workflow",
    "workflows",
    "skill",
    "skills",
    "codex",
    "claude",
    "pr",
    "issue",
    "repo",
    "repository",
    "codebase",
    "implement",
    "fix",
    "build",
    "create",
    "generate",
    "research",
    "paper",
    "arxiv",
    "doi",
    "link",
    "pdf",
    "image",
    "poster",
    "summary card",
    "회의",
    "요약",
    "논문",
    "링크",
    "이미지",
    "기능",
    "스킬",
    "워크플로",
    "헤르메스",
)


@dataclass(frozen=True)
class _SpecificCapabilityPhrase:
    skill: str
    phrase: str
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class ChatRouteDecision:
    schema_version: int
    source: str
    action: str
    selected_skill: str
    selected_harness: str
    candidate_skill: str
    candidate_harness: str
    confidence: str
    score: int
    threshold: str
    explicit: bool
    ambiguous: bool
    reason: str
    clarification: str
    routing_prompt: str
    task_card: dict[str, object] | None
    workflow_route_plan: dict[str, object] | None
    learning_candidate_card: dict[str, object] | None
    recommendations: tuple[dict[str, object], ...]
    route_next_action: str = ""

    def to_dict(self) -> dict[str, object]:
        payload = {
            "schema_version": self.schema_version,
            "source": self.source,
            "action": self.action,
            "selected_skill": self.selected_skill,
            "selected_harness": self.selected_harness,
            "candidate_skill": self.candidate_skill,
            "candidate_harness": self.candidate_harness,
            "confidence": self.confidence,
            "score": self.score,
            "threshold": self.threshold,
            "explicit": self.explicit,
            "ambiguous": self.ambiguous,
            "reason": self.reason,
            "clarification": self.clarification,
            "routing_prompt": self.routing_prompt,
            "task_card": dict(self.task_card) if self.task_card else None,
            "workflow_route_plan": self.workflow_route_plan,
            "learning_candidate_card": (
                dict(self.learning_candidate_card) if self.learning_candidate_card else None
            ),
            "recommendations": [dict(recommendation) for recommendation in self.recommendations],
        }
        if self.route_next_action:
            payload["route_next_action"] = self.route_next_action
        return payload


@dataclass(frozen=True)
class _CatalogFastPathResult:
    decision: ChatRouteDecision | None
    catalog_question: bool


def route_chat_message(
    message: str,
    *,
    source: str = "generic",
    limit: int = 3,
    min_confidence: str = "high",
) -> dict[str, object]:
    message = message.strip()
    if not message:
        raise ValueError("chat route requires a message")
    if source not in CHAT_SOURCES:
        raise ValueError(f"unsupported chat source: {source}")
    if limit < 1:
        raise ValueError("chat route --limit must be at least 1")
    if min_confidence not in CONFIDENCE_LEVELS:
        raise ValueError(f"unsupported chat route confidence threshold: {min_confidence}")

    return _clone_jsonish(_route_chat_message_cached(message, source, limit, min_confidence))


def public_chat_route_payload(
    message: str,
    *,
    source: str = "generic",
    limit: int = 3,
    min_confidence: str = "high",
    include_message: bool = False,
) -> dict[str, object]:
    message = message.strip()
    if not message:
        raise ValueError("chat route requires a message")
    if source not in CHAT_SOURCES:
        raise ValueError(f"unsupported chat source: {source}")
    if limit < 1:
        raise ValueError("chat route --limit must be at least 1")
    if min_confidence not in CONFIDENCE_LEVELS:
        raise ValueError(f"unsupported chat route confidence threshold: {min_confidence}")
    return _copy_public_route_payload(
        _public_chat_route_payload_cached(
            message,
            source,
            limit,
            min_confidence,
            include_message,
        )
    )


@lru_cache(maxsize=2048)
def _route_chat_message_cached(
    message: str,
    source: str,
    limit: int,
    min_confidence: str,
) -> dict[str, object]:
    routing_message = scrub_diagnostic_status_text(message)
    fast_omh_help_decision = _omh_help_fast_path_decision(
        message,
        routing_message=routing_message,
        source=source,
        min_confidence=min_confidence,
    )
    if fast_omh_help_decision is not None:
        return fast_omh_help_decision.to_dict()
    fast_maintenance_task_decision = _maintenance_task_fast_path_decision(
        message,
        routing_message=routing_message,
        source=source,
        min_confidence=min_confidence,
    )
    if fast_maintenance_task_decision is not None:
        return fast_maintenance_task_decision.to_dict()
    if not _is_specific_capability_question_shape(routing_message):
        for early_operator_skill in ("skill-scout", "skill-health"):
            fast_operator_decision = _operator_surface_fast_path_decision(
                message,
                routing_message=routing_message,
                source=source,
                min_confidence=min_confidence,
                allow_explicit_skill=True,
                only_skill=early_operator_skill,
            )
            if fast_operator_decision is not None:
                return fast_operator_decision.to_dict()
    fast_explicit_skill_decision = _explicit_skill_fast_path_decision(
        message,
        routing_message=routing_message,
        source=source,
        min_confidence=min_confidence,
    )
    if fast_explicit_skill_decision is not None:
        return fast_explicit_skill_decision.to_dict()
    fast_catalog_decision = _catalog_fast_path_decision(
        message,
        routing_message=routing_message,
        source=source,
        min_confidence=min_confidence,
    )
    if fast_catalog_decision.decision is not None:
        return fast_catalog_decision.decision.to_dict()
    fast_file_lookup_decision = _file_lookup_fast_path_decision(
        message,
        routing_message=routing_message,
        source=source,
        min_confidence=min_confidence,
    )
    if fast_file_lookup_decision is not None:
        return fast_file_lookup_decision.to_dict()
    fast_agent_ops_status_decision = _agent_ops_status_fast_path_decision(
        message,
        routing_message=routing_message,
        source=source,
        min_confidence=min_confidence,
    )
    if fast_agent_ops_status_decision is not None:
        return fast_agent_ops_status_decision.to_dict()
    fast_operator_surface_decision = _operator_surface_fast_path_decision(
        message,
        routing_message=routing_message,
        source=source,
        min_confidence=min_confidence,
    )
    if fast_operator_surface_decision is not None:
        return fast_operator_surface_decision.to_dict()
    fast_feedback_triage_decision = _feedback_triage_fast_path_decision(
        message,
        routing_message=routing_message,
        source=source,
        min_confidence=min_confidence,
    )
    if fast_feedback_triage_decision is not None:
        return fast_feedback_triage_decision.to_dict()
    fast_product_shaping_decision = _product_shaping_fast_path_decision(
        message,
        routing_message=routing_message,
        source=source,
        min_confidence=min_confidence,
    )
    if fast_product_shaping_decision is not None:
        return fast_product_shaping_decision.to_dict()
    fast_workflow_learning_decision = _workflow_learning_feedback_fast_path_decision(
        message,
        routing_message=routing_message,
        source=source,
        min_confidence=min_confidence,
    )
    if fast_workflow_learning_decision is not None:
        return fast_workflow_learning_decision.to_dict()
    fast_guarded_operator_decision = _guarded_operator_fast_path_decision(
        message,
        routing_message=routing_message,
        source=source,
        min_confidence=min_confidence,
    )
    if fast_guarded_operator_decision is not None:
        return fast_guarded_operator_decision.to_dict()
    fast_direct_answer_decision = _direct_answer_fast_path_decision(
        message,
        routing_message=routing_message,
        source=source,
        min_confidence=min_confidence,
    )
    if fast_direct_answer_decision is not None:
        return fast_direct_answer_decision.to_dict()

    definitions = routable_definitions()
    full_recommendations = recommend_skills(routing_message, limit=len(definitions))
    explicit_prefix = _has_explicit_invocation_prefix(routing_message)
    explicit_skill = explicit_skill_invocation(routing_message, definitions)
    if explicit_skill and not explicit_prefix and is_missed_route_feedback(routing_message):
        explicit_skill = None
    task_card = classify_task(message)
    task_card_overrides_explicit = _task_card_overrides_explicit_invocation(
        task_card,
        explicit_prefix=explicit_prefix,
    )
    if task_card and (not explicit_skill or task_card_overrides_explicit):
        full_recommendations = _prioritize_recommendation(full_recommendations, task_card_recommendation(task_card))
    catalog_question = fast_catalog_decision.catalog_question
    specific_catalog_match = (
        _specific_capability_catalog_match(full_recommendations, routing_message)
        if catalog_question and not _is_broad_capability_catalog_question(routing_message)
        else None
    )
    if specific_catalog_match is not None:
        full_recommendations = _prioritize_recommendation(full_recommendations, specific_catalog_match)
    browser_visual_qa_request = _browser_visual_qa_fast_path_signal(routing_message)
    customer_symptom_report = _customer_symptom_report_fast_path_signal(routing_message)
    if browser_visual_qa_request and not customer_symptom_report:
        visual_qa_match = _recommendation_for_skill(full_recommendations, "visual-qa")
        if visual_qa_match is not None:
            full_recommendations = _prioritize_recommendation(full_recommendations, visual_qa_match)
    recommendations = tuple(full_recommendations[:limit])
    top = full_recommendations[0]
    candidate_skill = str(top["skill"])
    candidate_harness = primary_harness_for_skill(candidate_skill)
    candidate_score = _int_value(top["score"])
    candidate_confidence = str(top["confidence"])
    ambiguous = _is_ambiguous(full_recommendations)
    explicit_loop_signal = _explicit_loop_signal(routing_message, full_recommendations)
    file_or_text_lookup = is_file_or_text_lookup_question(routing_message)
    direct_answer = _is_plain_direct_answer_question(
        routing_message,
        candidate_score=candidate_score,
    )

    if explicit_skill and not task_card_overrides_explicit:
        selected_skill = explicit_skill
        action = "dispatch"
        reason = "Explicit workflow invocation wins over heuristic routing."
        ambiguous = False
        task_card = None
    elif task_card:
        selected_skill = str(task_card.get("selected_workflow_rail", candidate_skill))
        candidate_skill = selected_skill
        candidate_harness = primary_harness_for_skill(candidate_skill)
        candidate_score = max(candidate_score, _int_value(task_card.get("score", 0)))
        candidate_confidence = str(task_card.get("confidence", "high"))
        action = "dispatch"
        reason = str(task_card.get("routing_reason", "Matched high-level task abstraction before workflow routing."))
        ambiguous = False
    elif catalog_question and specific_catalog_match is not None:
        selected_skill = candidate_skill
        action = "dispatch"
        reason = (
            f"Specific OMH capability question matched `{candidate_skill}`; "
            "show that workflow card instead of the generic workflow picker."
        )
        ambiguous = False
    elif catalog_question:
        selected_skill = _ROUTER_SKILL
        candidate_skill = selected_skill
        candidate_harness = primary_harness_for_skill(candidate_skill)
        candidate_score = max(candidate_score, 11)
        candidate_confidence = "high"
        action = "dispatch"
        reason = "Catalog question; show the OMH workflow picker instead of asking for shell command approval."
        ambiguous = False
    elif file_or_text_lookup:
        selected_skill = _ROUTER_SKILL
        candidate_skill = selected_skill
        candidate_harness = primary_harness_for_skill(candidate_skill)
        candidate_score = 0
        candidate_confidence = "low"
        action = "fallback"
        reason = FILE_LOOKUP_REASON
        ambiguous = False
    elif direct_answer:
        selected_skill = _ROUTER_SKILL
        candidate_skill = selected_skill
        candidate_harness = primary_harness_for_skill(candidate_skill)
        candidate_score = 0
        candidate_confidence = "low"
        action = "fallback"
        reason = DIRECT_ANSWER_REASON
        ambiguous = False
    elif explicit_loop_signal and candidate_skill != "img-summary":
        selected_skill = "loop"
        candidate_skill = selected_skill
        candidate_harness = primary_harness_for_skill(candidate_skill)
        candidate_score = max(candidate_score, 10)
        candidate_confidence = "high"
        action = "dispatch"
        reason = "Explicit loop invocation; start or continue the goal loop instead of opening a picker."
        ambiguous = False
    elif candidate_score == 0:
        selected_skill = _ROUTER_SKILL
        candidate_skill = selected_skill
        candidate_harness = primary_harness_for_skill(candidate_skill)
        action = "fallback"
        reason = "No strong catalog metadata match; use the router to clarify the workflow."
    elif ambiguous:
        selected_skill = _ROUTER_SKILL
        action = "clarify"
        reason = "Top catalog matches are tied; ask one concise clarification before dispatch."
    elif _meets_threshold(candidate_confidence, min_confidence):
        selected_skill = candidate_skill
        action = "dispatch"
        reason = str(top["why"])
    else:
        selected_skill = _ROUTER_SKILL
        action = "clarify"
        reason = f"Best match confidence {candidate_confidence} is below {min_confidence}; clarify before dispatch."

    selected_harness = primary_harness_for_skill(selected_skill)
    learning_candidate_card = build_learning_candidate_card(
        message,
        source=source,
        selected_workflow=selected_skill,
        selected_harness=selected_harness,
    )
    if (
        learning_candidate_card
        and selected_skill == "workflow-learning"
        and learning_candidate_card.get("recommended_workflow") != "workflow-learning"
    ):
        learning_candidate_card = None
    if learning_candidate_card:
        selected_skill = str(learning_candidate_card.get("recommended_workflow", selected_skill))
        selected_harness = primary_harness_for_skill(selected_skill)
        candidate_skill = selected_skill
        candidate_harness = selected_harness
        candidate_score = max(candidate_score, 12)
        candidate_confidence = "high"
        action = "dispatch"
        ambiguous = False
        reason = "Explicit learning signal; prepare a reviewable learning candidate card without running Hermes /learn."
        learning_candidate_card = build_learning_candidate_card(
            message,
            source=source,
            selected_workflow=selected_skill,
            selected_harness=selected_harness,
        )
    workflow_route_plan = build_workflow_route_plan(
        message,
        full_recommendations,
        selected_skill=selected_skill,
        action=action,
    )
    clarification = _clarification(action, candidate_skill, candidate_confidence, min_confidence, reason)
    route_next_action = _route_specific_next_action(
        routing_message,
        selected_skill=selected_skill,
        explicit_loop=explicit_loop_signal or explicit_loop_invocation_signal(routing_message),
    )
    decision = ChatRouteDecision(
        schema_version=1,
        source=source,
        action=action,
        selected_skill=selected_skill,
        selected_harness=selected_harness,
        candidate_skill=candidate_skill,
        candidate_harness=candidate_harness,
        confidence="high" if (explicit_skill and not task_card_overrides_explicit) or explicit_loop_signal else candidate_confidence,
        score=max(candidate_score, 1) if (explicit_skill and not task_card_overrides_explicit) or explicit_loop_signal else candidate_score,
        threshold=min_confidence,
        explicit=bool((explicit_skill and not task_card_overrides_explicit) or explicit_loop_signal),
        ambiguous=ambiguous,
        reason=reason,
        clarification=clarification,
        routing_prompt=_routing_prompt(action, selected_skill, candidate_skill, reason, message),
        task_card=task_card,
        workflow_route_plan=workflow_route_plan,
        learning_candidate_card=learning_candidate_card,
        recommendations=recommendations,
        route_next_action=route_next_action,
    )
    return decision.to_dict()


@lru_cache(maxsize=2048)
def _public_chat_route_payload_cached(
    message: str,
    source: str,
    limit: int,
    min_confidence: str,
    include_message: bool,
) -> dict[str, object]:
    return public_route_payload(
        _route_chat_message_cached(message, source, limit, min_confidence),
        include_message=include_message,
    )


def _clone_jsonish(value: Any) -> Any:
    value_type = type(value)
    if value_type is dict:
        return {key: _clone_jsonish(item) for key, item in value.items()}
    if value_type is list:
        return [_clone_jsonish(item) for item in value]
    if value_type is tuple:
        return tuple(_clone_jsonish(item) for item in value)
    return value


def _copy_public_route_payload(payload: dict[str, object]) -> dict[str, object]:
    route = dict(payload)
    route["recommendations"] = _copy_public_recommendations(route.get("recommendations", []))
    route_explanation = route.get("route_explanation")
    if isinstance(route_explanation, dict):
        route["route_explanation"] = _copy_route_explanation(route_explanation)
    workflow_route_plan = route.get("workflow_route_plan")
    if isinstance(workflow_route_plan, dict):
        route["workflow_route_plan"] = _copy_workflow_route_plan(workflow_route_plan)
    task_card = route.get("task_card")
    if isinstance(task_card, dict):
        route["task_card"] = _clone_jsonish(task_card)
    learning_candidate_card = route.get("learning_candidate_card")
    if isinstance(learning_candidate_card, dict):
        route["learning_candidate_card"] = _clone_jsonish(learning_candidate_card)
    return route


def _copy_public_recommendations(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    copied: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        recommendation = dict(item)
        matched = recommendation.get("matched")
        recommendation["matched"] = list(matched) if isinstance(matched, list) else []
        copied.append(recommendation)
    return copied


def _copy_route_explanation(value: dict[str, object]) -> dict[str, object]:
    copied = dict(value)
    not_evidence_yet = value.get("not_evidence_yet")
    copied["not_evidence_yet"] = list(not_evidence_yet) if isinstance(not_evidence_yet, list) else []
    return copied


def _copy_workflow_route_plan(value: dict[str, object]) -> dict[str, object]:
    copied = dict(value)
    steps = value.get("steps")
    copied["steps"] = [dict(item) for item in steps if isinstance(item, dict)] if isinstance(steps, list) else []
    stages = value.get("stages")
    copied["stages"] = list(stages) if isinstance(stages, list) else []
    return copied


def _omh_help_fast_path_decision(
    message: str,
    *,
    routing_message: str,
    source: str,
    min_confidence: str,
) -> ChatRouteDecision | None:
    if _has_explicit_invocation_prefix(routing_message):
        return None
    if explicit_skill_invocation(routing_message):
        return None
    if is_omh_quickstart_question(routing_message):
        return _router_help_decision(
            message,
            source=source,
            min_confidence=min_confidence,
            matched=("omh_quickstart_question",),
            next_action="show_quickstart",
            reason="OMH first-use or post-setup question; show the quickstart card instead of drafting a plan.",
            evidence_boundary=(
                "Quickstart output is local setup and wrapper guidance only; it is not host plugin load, "
                "executor work, review, CI, or merge evidence."
            ),
            wrapper_guidance="Render the OMH quickstart card with the smallest useful next action.",
            score=12,
        )
    if is_omh_status_question(routing_message) and not _is_specific_capability_question_shape(routing_message):
        return _router_help_decision(
            message,
            source=source,
            min_confidence=min_confidence,
            matched=("omh_status_question",),
            next_action="show_status",
            reason="OMH status or next-action question; show probe-backed status instead of drafting a plan.",
            evidence_boundary=(
                "Status and roadmap output is local probe evidence only; it is not host plugin load, executor work, "
                "review, CI, or merge evidence."
            ),
            wrapper_guidance="Render the OMH status card and only claim observed local probe results.",
            score=12,
        )
    if is_omh_intro_question(routing_message):
        return _router_help_decision(
            message,
            source=source,
            min_confidence=min_confidence,
            matched=("omh_intro_question",),
            next_action="show_context_brief",
            reason="OMH intro or usage question; show the compact Hermes-facing mental model before the full picker.",
            evidence_boundary=(
                "Context brief output is routing/help context only; it is not workflow execution, delivery, "
                "verification, review, CI, or merge evidence."
            ),
            wrapper_guidance="Render the OMH context brief first, then offer the workflow picker or quickstart card.",
            score=12,
        )
    return None


def _router_help_decision(
    message: str,
    *,
    source: str,
    min_confidence: str,
    matched: tuple[str, ...],
    next_action: str,
    reason: str,
    evidence_boundary: str,
    wrapper_guidance: str,
    score: int,
) -> ChatRouteDecision:
    selected_harness = primary_harness_for_skill(_ROUTER_SKILL)
    recommendation = _router_help_recommendation(
        message,
        matched=matched,
        next_action=next_action,
        reason=reason,
        evidence_boundary=evidence_boundary,
        wrapper_guidance=wrapper_guidance,
        score=score,
    )
    return ChatRouteDecision(
        schema_version=1,
        source=source,
        action="dispatch",
        selected_skill=_ROUTER_SKILL,
        selected_harness=selected_harness,
        candidate_skill=_ROUTER_SKILL,
        candidate_harness=selected_harness,
        confidence="high",
        score=score,
        threshold=min_confidence,
        explicit=False,
        ambiguous=False,
        reason=reason,
        clarification="",
        routing_prompt=_routing_prompt("dispatch", _ROUTER_SKILL, _ROUTER_SKILL, reason, message),
        task_card=None,
        workflow_route_plan=None,
        learning_candidate_card=None,
        recommendations=(recommendation,),
    )


def _router_help_recommendation(
    query: str,
    *,
    matched: tuple[str, ...],
    next_action: str,
    reason: str,
    evidence_boundary: str,
    wrapper_guidance: str,
    score: int,
) -> dict[str, object]:
    definition = _router_skill_definition()
    return {
        "skill": definition.name,
        "description": definition.description,
        "category": definition.category,
        "phase": definition.phase,
        "hermes_role": definition.hermes_role,
        "handoff_policy": definition.handoff_policy,
        "score": score,
        "confidence": "high",
        "matched": list(matched),
        "why": reason,
        "next_action": next_action,
        "evidence_boundary": evidence_boundary,
        "wrapper_guidance": wrapper_guidance,
        "suggested_prompt": query,
    }


def _maintenance_task_fast_path_decision(
    message: str,
    *,
    routing_message: str,
    source: str,
    min_confidence: str,
) -> ChatRouteDecision | None:
    task_card = classify_task(routing_message)
    if not task_card or task_card.get("task_type") != "omh_cli_maintenance":
        return None
    if _maintenance_task_should_yield_to_catalog(routing_message, task_card):
        return None
    selected_skill = str(task_card.get("selected_workflow_rail", _ROUTER_SKILL))
    selected_harness = primary_harness_for_skill(selected_skill)
    recommendation = _task_card_fast_path_recommendation(task_card, message)
    reason = str(
        task_card.get(
            "routing_reason",
            "Matched a short OMH CLI maintenance command; route as operator maintenance before scoring workflows.",
        )
    )
    score = _int_value(task_card.get("score", 12))
    confidence = str(task_card.get("confidence", "high"))
    return ChatRouteDecision(
        schema_version=1,
        source=source,
        action="dispatch",
        selected_skill=selected_skill,
        selected_harness=selected_harness,
        candidate_skill=selected_skill,
        candidate_harness=selected_harness,
        confidence=confidence,
        score=score,
        threshold=min_confidence,
        explicit=False,
        ambiguous=False,
        reason=reason,
        clarification="",
        routing_prompt=_routing_prompt("dispatch", selected_skill, selected_skill, reason, message),
        task_card=task_card,
        workflow_route_plan=None,
        learning_candidate_card=None,
        recommendations=(recommendation,),
    )


def _maintenance_task_should_yield_to_catalog(message: str, task_card: dict[str, object]) -> bool:
    if str(task_card.get("command", "")) != "list":
        return False
    compact = message.strip().lower().strip(" \t\r\n!?,;:。！？")
    if compact in _DIRECT_MAINTENANCE_LIST_COMMANDS:
        return False
    return is_catalog_without_shell_question(message) or is_skill_catalog_question(message)


def _task_card_fast_path_recommendation(task_card: dict[str, object], query: str) -> dict[str, object]:
    selected_skill = str(task_card.get("selected_workflow_rail", _ROUTER_SKILL))
    definition = _skill_definition_by_name(selected_skill)
    recommendation = task_card_recommendation(task_card)
    return {
        "skill": definition.name,
        "description": definition.description,
        "category": definition.category,
        "phase": definition.phase,
        "hermes_role": definition.hermes_role,
        "handoff_policy": definition.handoff_policy,
        **recommendation,
        "suggested_prompt": query,
    }


def _explicit_skill_fast_path_decision(
    message: str,
    *,
    routing_message: str,
    source: str,
    min_confidence: str,
) -> ChatRouteDecision | None:
    definitions = routable_definitions()
    selected_skill = explicit_skill_invocation(routing_message, definitions)
    if not selected_skill or selected_skill == _ROUTER_SKILL:
        return None
    if not _has_explicit_invocation_prefix(routing_message) and is_missed_route_feedback(routing_message):
        return None
    task_card = classify_task(routing_message)
    if _task_card_overrides_explicit_invocation(
        task_card,
        explicit_prefix=_has_explicit_invocation_prefix(routing_message),
    ):
        return None

    definition = _skill_definition_by_name(selected_skill)
    selected_harness = primary_harness_for_skill(selected_skill)
    reason = "Explicit workflow invocation wins over heuristic routing."
    recommendation = recommendation_for_definition(
        definition,
        message,
        matched=("explicit_invocation", f"name:{selected_skill}"),
        score=12,
        why=reason,
    )
    explicit_loop = selected_skill == "loop" and explicit_loop_invocation_signal(routing_message)
    route_next_action = _route_specific_next_action(
        routing_message,
        selected_skill=selected_skill,
        explicit_loop=explicit_loop,
    )
    return ChatRouteDecision(
        schema_version=1,
        source=source,
        action="dispatch",
        selected_skill=selected_skill,
        selected_harness=selected_harness,
        candidate_skill=selected_skill,
        candidate_harness=selected_harness,
        confidence="high",
        score=12,
        threshold=min_confidence,
        explicit=True,
        ambiguous=False,
        reason=reason,
        clarification="",
        routing_prompt=_routing_prompt("dispatch", selected_skill, selected_skill, reason, message),
        task_card=None,
        workflow_route_plan=None,
        learning_candidate_card=None,
        recommendations=(recommendation,),
        route_next_action=route_next_action,
    )


def _has_explicit_invocation_prefix(message: str) -> bool:
    first = message.strip().split(maxsplit=1)[0].strip(":,").lower()
    return first.startswith(("$", "/", "./", "@"))


def _catalog_fast_path_decision(
    message: str,
    *,
    routing_message: str,
    source: str,
    min_confidence: str,
) -> _CatalogFastPathResult:
    direct_picker = _direct_picker_alias(routing_message)
    catalog_question = False if direct_picker else is_skill_catalog_question(routing_message)
    specific_named_question = (
        not direct_picker
        and _is_specific_capability_question_shape(routing_message)
        and bool(_specific_capability_named_hits(routing_message))
    )
    catalog_question = catalog_question or specific_named_question
    exact_skill = (
        _specific_capability_exact_id_hit(routing_message)
        if catalog_question and not _is_broad_capability_catalog_question(routing_message)
        else None
    )
    if exact_skill is not None:
        return _specific_capability_fast_path_result(
            skill=exact_skill,
            message=message,
            source=source,
            min_confidence=min_confidence,
            matched=("catalog_question", f"name:{exact_skill}"),
            score=12,
            why=f"Matched exact OMH capability `{exact_skill}` from catalog metadata.",
            catalog_question=catalog_question,
        )
    alias_skill, alias_label = _specific_capability_alias_hit(routing_message)
    if catalog_question and alias_skill and not _is_broad_capability_catalog_question(routing_message):
        return _specific_capability_fast_path_result(
            skill=alias_skill,
            message=message,
            source=source,
            min_confidence=min_confidence,
            matched=("catalog_question", f"alias:{alias_label}"),
            score=11,
            why=f"Matched OMH capability alias `{alias_label}` from catalog metadata.",
            catalog_question=catalog_question,
        )
    catalog_picker = (
        not direct_picker
        and catalog_question
        and (
            is_catalog_without_shell_question(routing_message)
            or _generic_omh_catalog_question(routing_message)
        )
    )
    if not direct_picker and not catalog_picker:
        return _CatalogFastPathResult(decision=None, catalog_question=catalog_question)

    native_entrypoint_question = is_native_entrypoint_question(routing_message)
    native_next_action = (
        _native_entrypoint_next_action(routing_message)
        if native_entrypoint_question and not direct_picker
        else ""
    )
    matched = (
        ("direct_picker_alias",)
        if direct_picker
        else ("native_entrypoint_question",)
        if native_entrypoint_question
        else ("catalog_question",)
    )
    score = 12 if direct_picker else 11
    reason = (
        "Direct OMH picker alias; show the workflow picker without scoring every workflow."
        if direct_picker
        else "Native OMH entrypoint question; show the command preview or workflow picker without scoring every workflow."
        if native_entrypoint_question
        else "Catalog question; show the OMH workflow picker instead of asking for shell command approval."
    )
    selected_harness = primary_harness_for_skill(_ROUTER_SKILL)
    recommendation = _router_picker_recommendation(
        message,
        matched=matched,
        score=score,
        next_action=native_next_action or "choose_skill",
    )
    return _CatalogFastPathResult(
        decision=ChatRouteDecision(
            schema_version=1,
            source=source,
            action="dispatch",
            selected_skill=_ROUTER_SKILL,
            selected_harness=selected_harness,
            candidate_skill=_ROUTER_SKILL,
            candidate_harness=selected_harness,
            confidence="high",
            score=score,
            threshold=min_confidence,
            explicit=direct_picker,
            ambiguous=False,
            reason=reason,
            clarification="",
            routing_prompt=_routing_prompt("dispatch", _ROUTER_SKILL, _ROUTER_SKILL, reason, message),
            task_card=None,
            workflow_route_plan=None,
            learning_candidate_card=None,
            recommendations=(recommendation,),
        ),
        catalog_question=catalog_question,
    )


def _direct_picker_alias(message: str) -> bool:
    compact = message.strip().lower().strip(" \t\r\n!?,;:")
    return compact in _DIRECT_PICKER_ALIASES


def _specific_capability_fast_path_result(
    *,
    skill: str,
    message: str,
    source: str,
    min_confidence: str,
    matched: tuple[str, ...],
    score: int,
    why: str,
    catalog_question: bool,
) -> _CatalogFastPathResult:
    definition = _skill_definition_by_name(skill)
    matched = _specific_capability_fast_path_markers(skill, matched)
    recommendation = recommendation_for_definition(
        definition,
        message,
        matched=matched,
        score=score,
        why=why,
    )
    reason = (
        f"Specific OMH capability question matched `{skill}`; "
        "show that workflow card instead of the generic workflow picker."
    )
    selected_harness = primary_harness_for_skill(skill)
    return _CatalogFastPathResult(
        decision=ChatRouteDecision(
            schema_version=1,
            source=source,
            action="dispatch",
            selected_skill=skill,
            selected_harness=selected_harness,
            candidate_skill=skill,
            candidate_harness=selected_harness,
            confidence="high",
            score=score,
            threshold=min_confidence,
            explicit=False,
            ambiguous=False,
            reason=reason,
            clarification="",
            routing_prompt=_routing_prompt("dispatch", skill, skill, reason, message),
            task_card=None,
            workflow_route_plan=None,
            learning_candidate_card=None,
            recommendations=(recommendation,),
        ),
        catalog_question=catalog_question,
    )


def _specific_capability_fast_path_markers(skill: str, matched: tuple[str, ...]) -> tuple[str, ...]:
    if not any(marker.startswith("alias:") for marker in matched):
        return matched
    guard_by_skill = {
        "img-summary": "guard:img_summary",
        "paper-learning": "guard:paper_learning",
        "agent-debug": "guard:agent_debug",
        "instinct-ledger": "guard:instinct_ledger",
        "skill-scout": "guard:skill_scout",
        "skill-health": "guard:skill_health",
    }
    guard = guard_by_skill.get(skill)
    if not guard or guard in matched:
        return matched
    return (guard, *matched)


def _file_lookup_fast_path_decision(
    message: str,
    *,
    routing_message: str,
    source: str,
    min_confidence: str,
) -> ChatRouteDecision | None:
    if _has_explicit_invocation_prefix(routing_message):
        return None
    if explicit_skill_invocation(routing_message):
        return None
    if _operator_surface_fast_path_match(routing_message) is not None:
        return None
    if not is_file_or_text_lookup_question(routing_message):
        return None
    selected_harness = primary_harness_for_skill(_ROUTER_SKILL)
    reason = FILE_LOOKUP_REASON
    return ChatRouteDecision(
        schema_version=1,
        source=source,
        action="fallback",
        selected_skill=_ROUTER_SKILL,
        selected_harness=selected_harness,
        candidate_skill=_ROUTER_SKILL,
        candidate_harness=selected_harness,
        confidence="low",
        score=0,
        threshold=min_confidence,
        explicit=False,
        ambiguous=False,
        reason=reason,
        clarification=_clarification("fallback", _ROUTER_SKILL, "low", min_confidence, reason),
        routing_prompt=_routing_prompt("fallback", _ROUTER_SKILL, _ROUTER_SKILL, reason, message),
        task_card=None,
        workflow_route_plan=None,
        learning_candidate_card=None,
        recommendations=(_router_file_lookup_recommendation(message),),
    )


def _router_file_lookup_recommendation(query: str) -> dict[str, object]:
    definition = _router_skill_definition()
    return {
        "skill": definition.name,
        "description": definition.description,
        "category": definition.category,
        "phase": definition.phase,
        "hermes_role": definition.hermes_role,
        "handoff_policy": definition.handoff_policy,
        "score": 0,
        "confidence": "low",
        "matched": ["file_lookup_fast_path"],
        "why": FILE_LOOKUP_REASON,
        "next_action": "answer_file_lookup",
        "evidence_boundary": "No OMH workflow, execution, or file inspection has started.",
        "wrapper_guidance": "Answer as a file or text lookup; ask for the missing target if needed.",
        "suggested_prompt": query,
    }


def _agent_ops_status_fast_path_decision(
    message: str,
    *,
    routing_message: str,
    source: str,
    min_confidence: str,
) -> ChatRouteDecision | None:
    if _has_explicit_invocation_prefix(routing_message):
        return None
    if explicit_skill_invocation(routing_message):
        return None
    matched_phrase = _agent_ops_status_fast_path_match(routing_message)
    if not matched_phrase:
        return None
    selected_harness = primary_harness_for_skill(_AGENT_OPS_STATUS_FAST_PATH_SKILL)
    reason = (
        "Short status/progress question; show the Hermes agent ops review instead of a direct answer "
        "or gateway policy card."
    )
    definition = _skill_definition_by_name(_AGENT_OPS_STATUS_FAST_PATH_SKILL)
    recommendation = recommendation_for_definition(
        definition,
        message,
        matched=("agent_ops_status_fast_path", f"phrase:{matched_phrase}"),
        score=14,
        why=reason,
    )
    return ChatRouteDecision(
        schema_version=1,
        source=source,
        action="dispatch",
        selected_skill=_AGENT_OPS_STATUS_FAST_PATH_SKILL,
        selected_harness=selected_harness,
        candidate_skill=_AGENT_OPS_STATUS_FAST_PATH_SKILL,
        candidate_harness=selected_harness,
        confidence="high",
        score=14,
        threshold=min_confidence,
        explicit=False,
        ambiguous=False,
        reason=reason,
        clarification="",
        routing_prompt=_routing_prompt(
            "dispatch",
            _AGENT_OPS_STATUS_FAST_PATH_SKILL,
            _AGENT_OPS_STATUS_FAST_PATH_SKILL,
            reason,
            message,
        ),
        task_card=None,
        workflow_route_plan=None,
        learning_candidate_card=None,
        recommendations=(recommendation,),
    )


def _agent_ops_status_fast_path_match(message: str) -> str | None:
    value = unicodedata.normalize("NFC", message)
    text = re.sub(r"\s+", " ", value.strip().lower().strip(" \t\r\n.!?,;:~…？"))
    if text in _AGENT_OPS_STATUS_FAST_PATH_EXACT_PHRASES:
        return text
    compact = re.sub(r"[\s\?\!\.,;:~…？]+", "", value.strip().lower())
    if compact in _AGENT_OPS_STATUS_FAST_PATH_COMPACT_PHRASES:
        return compact
    return None


_OPERATOR_SURFACE_FAST_PATH_RULES: tuple[tuple[str, tuple[str, ...], str, str], ...] = (
    (
        "ralplan",
        (
            "safely add a feature",
            "safe feature work",
            "add a feature safely",
            "risky refactor",
            "risky refactoring",
            "안전하게 기능 추가",
            "안전하게 기능을 추가",
            "सुरक्षित तरीके से नई सुविधा जोड़",
            "नई सुविधा सुरक्षित तरीके से जोड़",
            "위험한 리팩터링",
            "위험한 리팩토링",
        ),
        "operator_surface_fast_path:planning",
        "Clear safe-change or risky-refactor request; prepare a reviewed plan before implementation or cleanup.",
    ),
    (
        "img-summary",
        (
            "meeting image card",
            "meeting summary image",
            "pr summary image",
            "issue summary card",
            "release announcement card",
            "image card",
            "make a thumbnail",
            "create a thumbnail",
            "generate a thumbnail",
            "thumbnail card",
            "release thumbnail",
            "이미지 생성해줘",
            "이미지 요약 카드",
            "이미지 카드 만들어",
            "이미지 카드로 만들어",
            "이미지 카드로 요약",
            "이미지로 만들어줘",
            "회의록을 이미지 카드",
            "회의록을 세로 카드",
            "회의록 요약 이미지",
            "pr 요약 이미지",
            "릴리즈 노트 이미지",
            "크론 설명 이미지",
            "이슈 요약 카드",
            "썸네일 만들어줘",
            "썸네일 생성해줘",
            "썸네일로 만들어줘",
            "릴리즈 노트 썸네일",
        ),
        "operator_surface_fast_path:visual",
        "Clear thumbnail or release-thumbnail request; prepare the image prompt-card workflow without scoring every workflow.",
    ),
    (
        "paper-learning",
        (
            "paper summary",
            "explain this paper",
            "explain this pdf",
            "paper pdf explanation",
            "paper pdf expert explanation",
            "paper at beginner level",
            "pdf paper at beginner level",
            "this pdf paper",
            "explain this pdf paper",
            "attached paper",
            "attached paper at beginner level",
            "attached paper easy",
            "논문 요약",
            "논문 pdf 이해",
            "논문 pdf 설명",
            "pdf 논문 설명",
            "pdf 논문",
            "이 pdf 논문",
            "논문 초보자",
            "논문 해설",
            "논문 풀어",
            "논문 쉽게 설명",
            "paper를 쉬운",
            "paper 쉬운",
            "첨부한 paper",
            "첨부한 논문",
            "pdf 쉽게 설명",
            "pdf 쉽게 요약",
            "이 pdf 쉽게 설명",
            "이 pdf 쉽게 요약",
        ),
        "operator_surface_fast_path:paper",
        "Clear paper or paper-PDF explanation request; prepare paper-learning without scoring every workflow.",
    ),
    (
        "operating-rhythm",
        (
            "meeting notes cleanup",
            "meeting minutes cleanup",
            "organize meeting notes",
            "회의록 정리",
            "회의록 관리",
            "회의록 히스토리",
            "스크럼 회고 정리",
            "스프린트 회고 정리",
        ),
        "operator_surface_fast_path:operating",
        "Clear meeting-record or operating-rhythm request; prepare the operating record without scoring every workflow.",
    ),
    (
        "design-quality-gate",
        (
            "design quality gate",
            "design qa",
            "layout qa",
            "visual design review",
            "make this look polished",
            "make this look less generic",
            "make this ui look premium",
            "디자인 품질",
            "디자인 qa",
            "디자인 검증",
            "레이아웃 qa",
            "레이아웃 검증",
            "디자인 레이아웃 qa",
            "이쁘고 잘나오게",
            "예쁘고 잘 나오게",
            "ai 티 안 나게",
        ),
        "operator_surface_fast_path:design_quality",
        "Clear design-quality or layout-polish request; prepare the quality gate before implementation or visual PASS claims.",
    ),
    (
        "frontend",
        (
            "frontend handoff",
            "frontend implementation handoff",
            "frontend layout",
            "responsive frontend",
            "web ui layout",
            "webpage layout",
            "프론트엔드 handoff",
            "프론트엔드 핸드오프",
            "프론트엔드 구현",
            "웹페이지 레이아웃",
            "웹 ui 레이아웃",
            "반응형 프론트엔드",
        ),
        "operator_surface_fast_path:frontend",
        "Clear frontend design or implementation-handoff request; prepare frontend scope, states, breakpoints, and visual-QA follow-up boundaries.",
    ),
    (
        "accessibility-audit",
        (
            "accessibility audit",
            "wcag audit",
            "wcag check",
            "screen reader check",
            "keyboard focus check",
            "touch target check",
            "접근성 감사",
            "접근성 점검",
            "접근성 체크",
            "wcag 체크",
            "스크린리더",
            "키보드 포커스",
            "터치 타깃",
        ),
        "operator_surface_fast_path:accessibility",
        "Clear accessibility or WCAG request; prepare observed-only accessibility audit boundaries before PASS claims.",
    ),
    (
        "visual-qa",
        (
            "visual qa",
            "screenshot qa",
            "pixel diff",
            "layout broken",
            "rendered page check",
            "visual regression",
            "화면 깨지는지",
            "스크린샷 기준",
            "픽셀 diff",
            "픽셀 차이",
            "시각 qa",
        ),
        "operator_surface_fast_path:visual_qa",
        "Clear rendered visual QA request; prepare screenshot, diff, viewport, CJK, and verdict evidence slots.",
    ),
    (
        "web-research",
        (
            "web search",
            "web research",
            "latest sources",
            "latest evidence",
            "current sources",
            "source backed research",
            "웹서치",
            "웹 리서치",
            "최신 자료",
            "최신 근거",
            "최신 정보",
            "근거 찾아",
            "자료 조사",
            "자료 찾아",
            "자료 찾아줘",
        ),
        "operator_surface_fast_path:research",
        "Clear web/current-source research request; start Hermes-owned source-backed research without scoring every workflow.",
    ),
    (
        "source-finder",
        (
            "find papers datasets",
            "find papers datasets github",
            "find public presentations",
            "find arxiv link",
            "find arxiv paper",
            "paper pdf 찾아",
            "paper pdf를 찾아",
            "paper pdf 찾아서",
            "pdf 자료 찾아",
            "public pdf sources",
            "find public pdf",
            "arxiv link",
            "github oss repo",
            "github repos and public presentations",
            "자료 출처 찾아",
            "데이터셋이랑 깃허브",
            "데이터셋 찾아",
            "깃허브 오픈소스 찾아",
            "깃허브 오픈소스 저장소 찾아",
            "공개 데이터셋 찾아",
            "논문 링크 찾아",
            "논문 링크 찾아줘",
            "논문 pdf 링크 찾아",
            "arxiv 링크 찾아",
            "arxiv 링크 찾아서",
            "깃허브 repo 소스 찾아",
            "깃허브 리포 소스 찾아",
            "깃허브 저장소 찾아",
            "오픈소스 저장소 찾아",
            "깃허브 저장소 찾아서",
            "github repo 소스 찾아",
            "github repository 소스 찾아",
        ),
        "operator_surface_fast_path:source",
        "Clear source-acquisition request; scope source candidates before explanation or downstream work.",
    ),
    (
        "codebase-onboarding",
        (
            "codebase onboarding",
            "repo onboarding",
            "repository onboarding",
            "codebase tour",
            "new repo orientation",
            "understand this repo",
            "how this repo works",
            "first-read onboarding",
            "first-read onboarding path",
            "first-read repo",
            "first-read codebase",
            "repo reading path",
            "reading path for this repo",
            "레포 온보딩",
            "코드베이스 온보딩",
            "처음 보는 레포",
            "처음 보는 repo",
            "처음 보는 repository",
            "레포 구조 설명",
        ),
        "operator_surface_fast_path:codebase_onboarding",
        "Clear repo onboarding or first-read request; prepare the reading path before refresh-only codegraph work.",
    ),
    (
        "ultraprocess",
        (
            "codex issue pr",
            "codex로 이 이슈 pr",
            "codex로 이슈 pr",
            "코덱스로 이 이슈 pr",
            "코덱스로 이슈 pr",
            "코덱스로 이 이슈 pr 만들어",
            "merge as friren",
            "merge with friren author",
            "friren author",
            "friren author로",
            "프리렌 author",
            "프리렌 author로",
            "프리렌 author로 머지",
            "프리렌 author로 커밋",
            "프리렌으로 머지",
            "프리렌으로 커밋",
            "improve readme",
            "update readme",
            "readme improvement",
            "리드미 개선",
            "readme 개선",
        ),
        "operator_surface_fast_path:delivery",
        "Clear executor-backed issue-to-PR request; prepare the one-cycle delivery path.",
    ),
    (
        "performance-goal",
        (
            "performance optimization",
            "optimize performance",
            "improve latency",
            "benchmark latency",
            "성능 최적화",
            "성능 개선",
            "레이턴시 개선",
            "레이턴시 최적화",
        ),
        "operator_surface_fast_path:performance",
        "Clear performance-improvement request; prepare the measured performance goal without scoring every workflow.",
    ),
    (
        "doctor",
        (
            "did update work",
            "update worked",
            "update version unchanged",
            "version unchanged after update",
            "omh update worked",
            "omh update 했는데 잘",
            "update 했는데 잘",
            "update 했는데 버전",
            "업데이트 했는데 잘",
            "업데이트했는데 잘",
            "업데이트 했는데 버전",
            "업데이트했는데 버전",
        ),
        "operator_surface_fast_path:doctor",
        "Clear OMH setup/update health question; run diagnostics without scoring every workflow.",
    ),
    (
        "github-event-ops",
        (
            "pr opened ci failed",
            "pr opened and ci failed",
            "ci failed on pr",
            "ci failed on my pr",
            "pr opened review failed",
            "github pr ci failed",
            "pr 열렸는데 ci 실패",
            "pr이 열렸는데 ci 실패",
            "ci 실패했어 정리",
            "ci 실패 원인",
            "pr ci 실패",
        ),
        "operator_surface_fast_path:github_event",
        "Clear PR/CI event request; prepare GitHub event ops without scoring every workflow.",
    ),
    (
        "memory-curation-review",
        (
            "hermes remembers incorrectly",
            "hermes remembered incorrectly",
            "hermes is remembering wrong",
            "hermes remembers this wrong",
            "hermes memory is wrong",
            "hermes가 내 기억을 잘못",
            "헤르메스가 내 기억을 잘못",
            "hermes가 기억을 잘못",
            "헤르메스가 기억을 잘못",
            "memory가 잘못 저장",
            "memory 잘못 저장",
            "메모리가 잘못 저장",
            "메모리 잘못 저장",
            "기억이 잘못 저장",
            "기억 잘못 저장",
            "내 메모리 뭐가 저장",
            "내 기억 뭐가 저장",
        ),
        "operator_surface_fast_path:memory",
        "Clear Hermes memory-context review request; prepare memory curation without scoring every workflow.",
    ),
    (
        "executor-runtime-readiness",
        (
            "open in codex",
            "open codex",
            "start codex session",
            "create codex session",
            "open in claude code",
            "start claude code session",
            "create claude code session",
            "claude code connected",
            "codex로 열어줘",
            "codex로 새 세션",
            "codex로 지금 작업 열어",
            "codex로 현재 작업 열어",
            "codex 세션 열어",
            "codex 세션 열고",
            "codex 새 세션",
            "codex 세션 켜",
            "codex 세션 시작",
            "codex 세션 만들어",
            "코덱스 세션 열어",
            "코덱스 세션 열고",
            "코덱스 새 세션",
            "코덱스 세션 켜",
            "코덱스 세션 시작",
            "코덱스 세션 만들어",
            "코덱스로 열어줘",
            "코덱스로 새 세션",
            "코덱스로 지금 작업 열어",
            "코덱스로 현재 작업 열어",
            "코덱스로 현재 작업 이어서",
            "코덱스로 지금 작업 이어서",
            "claude code로 이어서",
            "claude code로 새 세션",
            "claude code로 지금 작업 열어",
            "claude code로 현재 작업 열어",
            "claude code 세션 시작",
            "claude code 연결",
            "claude code 세션 연결",
            "claude code 세션 연결해서",
            "클로드 코드 연결",
            "클로드 코드 세션 연결",
            "클로드 코드 세션 연결해서",
            "클로드 코드로 이어서",
            "클로드 코드로 새 세션",
            "클로드 코드로 지금 작업 열어",
            "클로드 코드로 현재 작업 열어",
            "클로드 코드 세션 시작",
            "코딩 에이전트 뭘로 설정",
            "코딩 에이전트 뭐로 설정",
            "coding agent configured",
            "coding agent setting",
        ),
        "operator_surface_fast_path:executor",
        "Clear coding-agent readiness request; show the selected executor/runtime path without scoring every workflow.",
    ),
    (
        "materials-package",
        (
            "materials-package",
            "material package",
            "make a ppt",
            "make slides",
            "turn into slides",
            "make a deck",
            "slide deck",
            "speaker notes",
            "spreadsheet dashboard",
            "summary tab",
            "export to pdf and ppt",
            "ppt 만들어줘",
            "발표자료로 만들어줘",
            "발표 자료로 만들어줘",
            "발표용 pptx",
            "발표자 노트",
            "엑셀을 월간 보고서",
            "엑셀 파일로 kpi 대시보드",
            "차트랑 요약 탭",
            "pdf랑 ppt",
        ),
        "operator_surface_fast_path:materials",
        "Clear materials or document-package request; prepare the file/package workflow without scoring every workflow.",
    ),
    (
        "command-operator",
        (
            "command operator",
            "terminal command",
            "terminal task",
            "shell command",
            "shell task",
            "cli command",
            "command execution",
            "run command",
            "run this command",
            "execute command",
            "execute this command",
            "run npm test",
            "run tests",
            "npm test",
            "pnpm test",
            "bun test",
            "uv run",
            "python -m unittest",
            "pytest",
            "make test",
            "cargo test",
            "go test",
            "summarize command output",
            "터미널 명령",
            "터미널에서",
            "셸 명령",
            "쉘 명령",
            "명령 실행",
            "명령어 실행",
            "실행 준비",
            "npm test 실행",
            "테스트 실행",
            "결과 요약",
        ),
        "operator_surface_fast_path:command_operator",
        "Clear terminal/CLI command request; prepare command scope, safety gates, cwd, timeout, and observed-result boundaries without scoring every workflow.",
    ),
    (
        "connector-operator",
        (
            "connector operator",
            "external app action",
            "external connector action",
            "send an email",
            "send the email",
            "send email",
            "email customer",
            "gmail draft",
            "gmail send",
            "create linear ticket",
            "create linear issue",
            "linear ticket",
            "linear issue",
            "update linear",
            "jira ticket",
            "jira issue",
            "create jira issue",
            "open jira ticket",
            "notion page",
            "update notion",
            "crm update",
            "calendar invite",
            "google calendar",
            "send slack dm",
            "slack dm",
            "discord dm",
            "post to discord",
            "post to slack",
            "discord post",
            "slack post",
            "connector action",
            "이메일 보내",
            "이메일 발송",
            "메일 보내",
            "gmail 초안",
            "linear ticket",
            "linear 티켓",
            "linear 이슈",
            "jira 티켓",
            "jira 이슈",
            "notion 페이지",
            "노션 페이지",
            "캘린더 초대",
            "외부 앱",
            "외부 커넥터",
        ),
        "operator_surface_fast_path:connector_operator",
        "Clear external app or SaaS connector action request; prepare provider, auth, target, payload, confirmation, and observed-result boundaries without scoring every workflow.",
    ),
    (
        "live-info-operator",
        (
            "live info operator",
            "live information",
            "weather today",
            "current weather",
            "weather forecast",
            "stock price",
            "crypto price",
            "btc price",
            "exchange rate",
            "sports score",
            "game score",
            "time zone",
            "timezone",
            "time in",
            "map directions",
            "directions to",
            "near me",
            "traffic now",
            "오늘 날씨",
            "현재 날씨",
            "날씨 예보",
            "주가",
            "코인 가격",
            "환율",
            "스포츠 점수",
            "경기 결과",
            "시간대",
            "현재 시간",
            "지도",
            "길찾기",
        ),
        "operator_surface_fast_path:live_info",
        "Clear live information lookup request; prepare provider, freshness, units, source-quality, and observed-result boundaries without scoring every workflow.",
    ),
    (
        "content-operator",
        (
            "content operator",
            "content workflow",
            "writing workflow",
            "publish-ready writing",
            "publish ready writing",
            "release notes",
            "release note draft",
            "newsletter draft",
            "customer announcement",
            "customer copy",
            "product copy",
            "landing page copy",
            "social post draft",
            "email draft",
            "draft an email",
            "rewrite for executives",
            "summarize for customers",
            "style guide rewrite",
            "audience and tone",
            "tone of voice",
            "콘텐츠 오퍼레이터",
            "글쓰기 워크플로",
            "릴리즈 노트",
            "릴리즈노트",
            "뉴스레터 초안",
            "고객 공지문",
            "고객 공지",
            "고객용 요약",
            "메일 초안",
            "이메일 초안",
            "채널별 톤",
            "문체 가이드",
        ),
        "operator_surface_fast_path:content_operator",
        "Clear quality-controlled content request; prepare source scope, audience, tone, review, hallucination, and output-evidence boundaries without scoring every workflow.",
    ),
    (
        "media-input-operator",
        (
            "media input operator",
            "media input",
            "audio transcription",
            "audio transcript",
            "transcribe audio",
            "transcribe this audio",
            "meeting recording",
            "recording transcript",
            "video transcript",
            "youtube summary",
            "youtube video",
            "summarize youtube",
            "summarize this youtube",
            "video summary",
            "summarize this video",
            "with timestamps",
            "clip summary",
            "podcast summary",
            "webinar summary",
            "오디오 전사",
            "음성 전사",
            "회의 녹음",
            "녹음 요약",
            "영상 요약",
            "유튜브 요약",
            "youtube 요약",
            "타임스탬프",
            "타임라인 요약",
        ),
        "operator_surface_fast_path:media_input",
        "Clear media input request; prepare source, permission, transcript, timestamp, and observed-result boundaries without scoring every workflow.",
    ),
    (
        "data-analysis",
        (
            "analyze this csv",
            "analyze csv",
            "csv analysis",
            "csv data analysis",
            "analyze json",
            "json analysis",
            "json log analysis",
            "log analysis",
            "analyze logs",
            "summarize anomalies",
            "anomalies by segment",
            "trend analysis",
            "segment analysis",
            "schema check",
            "column analysis",
            "csv 매출 데이터를 분석",
            "데이터 분석",
            "데이터를 분석",
            "csv 분석",
            "json 로그를 분석",
            "json 분석",
            "로그 분석",
            "오류 패턴",
            "이상치",
            "추세를 요약",
            "추세 분석",
            "컬럼 분석",
        ),
        "operator_surface_fast_path:data_analysis",
        "Clear supplied data/table/log analysis request; prepare dataset scope, method, and evidence boundaries without scoring every workflow.",
    ),
    (
        "workspace-file-operator",
        (
            "list files",
            "list folder",
            "list directory",
            "find local files",
            "search files in folder",
            "organize files",
            "organize folder",
            "move old pdfs",
            "move files",
            "copy files",
            "rename files",
            "delete files",
            "remove files",
            "archive files",
            "downloads folder file cleanup",
            "reports folder",
            "folder cleanup",
            "file cleanup",
            "다운로드 폴더 파일 정리",
            "다운로드 폴더 정리",
            "폴더 파일 정리",
            "파일 정리해줘",
            "파일 삭제 전 확인",
            "오래된 zip 삭제",
            "파일 이동",
            "파일 복사",
            "파일 이름 변경",
            "디렉터리 목록",
        ),
        "operator_surface_fast_path:workspace_file",
        "Clear local file or folder operation request; prepare path scope and destructive-operation boundaries without scoring every workflow.",
    ),
    (
        "workspace-audit",
        (
            "workspace audit",
            "audit this workspace",
            "workspace inventory",
            "agent workspace audit",
            "prompts skills plugins hooks",
            "skills prompts plugins hooks",
            "prompt skill plugin hook inventory",
            "워크스페이스 감사",
            "워크스페이스 점검",
            "스킬 프롬프트 플러그인 훅",
            "프롬프트 스킬 플러그인 훅",
        ),
        "operator_surface_fast_path:workspace_audit",
        "Clear workspace inventory or audit request; prepare read-only surface mapping before repair or mutation.",
    ),
    (
        "agent-evaluation",
        (
            "agent evaluation",
            "agent eval",
            "compare agent outputs",
            "compare codex and claude",
            "compare codex vs claude",
            "same task rubric",
            "rubric and metrics",
            "executor benchmark",
            "에이전트 평가",
            "에이전트 비교",
            "codex와 claude code를 같은",
            "코덱스와 클로드 코드를 같은",
            "루브릭과 메트릭",
        ),
        "operator_surface_fast_path:agent_evaluation",
        "Clear executor or agent evaluation request; prepare reproducible tasks, rubric, metrics, and evidence boundaries.",
    ),
    (
        "rules-distill",
        (
            "rules distill",
            "rule candidates",
            "agents.md rule candidates",
            "add to agents.md",
            "repeated failure into rules",
            "distill repeated lessons",
            "반복 실수",
            "규칙 후보",
            "agents.md 규칙",
            "agent.md 규칙",
            "스킬 규칙 후보",
            "반복 원칙 후보",
        ),
        "operator_surface_fast_path:rules_distill",
        "Clear request to turn repeated lessons into reviewed rules; prepare candidates without mutating guidance automatically.",
    ),
    (
        "harness-session-inventory",
        (
            "harness session inventory",
            "session inventory",
            "session adapter",
            "session adapters",
            "mcp inventory",
            "mcp config inventory",
            "mcp drift",
            "harness drift",
            "connector drift",
            "worktree inventory",
            "worktree lifecycle",
            "operator inventory",
            "control pane inventory",
            "codex session inventory",
            "claude code session inventory",
            "세션 인벤토리",
            "하네스 세션",
            "하네스 드리프트",
            "mcp 인벤토리",
            "mcp 설정 드리프트",
            "워크트리 인벤토리",
            "커넥터 드리프트",
        ),
        "operator_surface_fast_path:harness_inventory",
        "Clear harness/session/MCP inventory request; prepare the drift-aware inventory without scoring every workflow.",
    ),
    (
        "context-budget-review",
        (
            "context-budget-review",
            "context budget review",
            "context budget",
            "token budget review",
            "token budget",
            "prompt budget",
            "context compaction",
            "compact context",
            "summarization checkpoint",
            "budget this task",
            "컨텍스트 예산",
            "토큰 예산",
            "컨텍스트 압축",
            "요약 체크포인트",
        ),
        "operator_surface_fast_path:context_budget",
        "Clear context or token budget request; prepare the context budget review without treating token burn as agent failure.",
    ),
    (
        "instinct-ledger",
        (
            "instinct-ledger",
            "instinct ledger",
            "project instincts",
            "project-scoped instincts",
            "project scoped instincts",
            "global instincts",
            "instinct review",
            "instinct candidate",
            "instinct candidates",
            "instinct promotion",
            "promote instinct",
            "promote learning",
            "confidence scored learning",
            "confidence-scored learning",
            "project learning patterns",
            "cross-project learning",
            "export instincts",
            "import instincts",
            "학습 본능",
            "프로젝트별 학습",
            "프로젝트 스코프 학습",
            "전역 학습 승격",
            "학습 승격",
            "학습 패턴 승격",
        ),
        "operator_surface_fast_path:instinct_ledger",
        "Clear project/global instinct learning request; prepare scoped instinct candidates without automatic hooks, writes, or promotion.",
    ),
    (
        "agent-debug",
        (
            "agent-debug",
            "agent debug",
            "agent debugging",
            "agent introspection",
            "agent self-debug",
            "agent failure capture",
            "agent run stuck",
            "agent loop failure",
            "agent looping",
            "looping agent",
            "tool retry loop",
            "repeated tool calls",
            "repeating the same command",
            "agent context drift",
            "prompt drift",
            "agent token burn",
            "agent burning tokens",
            "agent stopped",
            "agent stuck",
            "agent가 왜",
            "agent 멈",
            "에이전트 디버그",
            "에이전트 실패",
            "에이전트가 왜",
            "에이전트 멈",
            "에이전트 반복 실패",
            "반복 실패",
            "도구 반복",
            "컨텍스트 드리프트",
            "토큰 낭비",
        ),
        "operator_surface_fast_path:agent_debug",
        "Clear stuck, looping, or drifting agent-run request; prepare failure capture and contained recovery guidance without hidden reset.",
    ),
    (
        "skill-scout",
        (
            "skill-scout",
            "skill scout",
            "skill candidate",
            "skill candidate search",
            "skill discovery",
            "find a skill",
            "find skills",
            "is there a skill",
            "existing skill",
            "fork a skill",
            "extend a skill",
            "create skill after search",
            "new skill search",
            "skill adoption",
            "스킬 스카우트",
            "스킬 후보",
            "스킬 찾기",
            "스킬 검색",
            "스킬 만들기 전",
            "기존 스킬",
        ),
        "operator_surface_fast_path:skill_scout",
        "Clear skill candidate search-before-creation request; prepare a scout report without installing, copying, or trusting candidates.",
    ),
    (
        "skill-health",
        (
            "skill-health",
            "skill health",
            "skill portfolio health",
            "skill health dashboard",
            "skill dashboard",
            "skill portfolio dashboard",
            "skill failure pattern dashboard",
            "pending skill amendments",
            "스킬 헬스",
            "스킬 상태",
            "스킬 대시보드",
            "스킬 실패 패턴",
            "스킬 보류 수정",
        ),
        "operator_surface_fast_path:skill_health",
        "Clear skill portfolio health request; prepare the dashboard without treating it as install repair or automatic skill mutation.",
    ),
    (
        "automation-blueprint",
        (
            "automate this",
            "automate workflow",
            "daily digest automation",
            "prepare a daily digest",
            "send a daily digest",
            "매일 아침 리서치 요약",
            "매일 아침 경쟁사 뉴스",
            "매일 아침 뉴스 요약",
            "매일아침 리서치 요약",
            "매일아침 경쟁사 뉴스",
            "아침마다 리서치 요약을 보내",
            "아침마다 뉴스 요약을 보내",
            "내일 아침마다 요약",
            "요약을 보내게",
            "자동화해줘",
            "자동화 해줘",
            "자동화하는 흐름",
        ),
        "operator_surface_fast_path:automation",
        "Clear automation request; prepare the scheduled-ops blueprint without scoring every workflow.",
    ),
    (
        "agent-board",
        (
            "multiple hermes agents",
            "multiple hermes profiles",
            "multi agent topology",
            "target topology",
            "agent topology",
            "hermes agent 여러",
            "헤르메스 agent 여러",
            "헤르메스 에이전트 여러",
            "에이전트가 한개가 아니라 여러개",
            "에이전트가 한 개가 아니라 여러 개",
            "agent가 한개가 아니라 여러개",
            "agent가 한 개가 아니라 여러 개",
        ),
        "operator_surface_fast_path:agent_board",
        "Clear multi-Hermes-agent topology request; prepare the board/status contract without scoring every workflow.",
    ),
)


def _operator_surface_fast_path_decision(
    message: str,
    *,
    routing_message: str,
    source: str,
    min_confidence: str,
    allow_explicit_skill: bool = False,
    only_skill: str | None = None,
) -> ChatRouteDecision | None:
    if _has_explicit_invocation_prefix(routing_message):
        return None
    if not allow_explicit_skill and explicit_skill_invocation(routing_message):
        return None
    match = _operator_surface_fast_path_match(routing_message, only_skill=only_skill)
    if match is None:
        return None
    selected_skill, phrase, marker, reason = match
    if only_skill is not None and selected_skill != only_skill:
        return None
    if selected_skill == "ralplan" and _is_fast_plain_direct_answer_question(routing_message):
        return None
    if selected_skill == "paper-learning" and (
        _is_paper_learning_citation_research_request(routing_message)
        or _is_paper_learning_materials_request(routing_message)
    ):
        return None
    if selected_skill == "command-operator" and _is_command_operator_failure_or_coding_request(routing_message):
        return None
    if selected_skill == "connector-operator" and _is_connector_operator_setup_or_gateway_request(routing_message):
        return None
    if selected_skill == "live-info-operator" and _is_live_info_operator_setup_or_research_request(routing_message):
        return None
    if selected_skill == "content-operator" and _is_content_operator_research_connector_or_materials_request(routing_message):
        return None
    if selected_skill == "skill-scout" and _is_installed_skill_repair_request(routing_message):
        selected_skill = "doctor"
        phrase = "installed skill repair"
        marker = "operator_surface_fast_path:doctor"
        reason = "Installed skill setup or repair request; run diagnostics instead of scouting new candidates."
    if _operator_surface_guard_preempts(
        selected_skill,
        routing_message,
        preempting_skills=("source-finder", "toolbelt-readiness"),
    ):
        return None
    selected_harness = primary_harness_for_skill(selected_skill)
    definition = _skill_definition_by_name(selected_skill)
    extra_markers = _operator_surface_extra_markers(selected_skill, phrase)
    matched = (marker, *extra_markers, _operator_surface_phrase_marker(marker, phrase))
    score = _operator_surface_score(selected_skill, extra_markers)
    why = _operator_surface_reason(reason, extra_markers)
    recommendation = recommendation_for_definition(
        definition,
        message,
        matched=matched,
        score=score,
        why=why,
    )
    route_next_action = ""
    if "guard:merge_author_constraint" in extra_markers:
        route_next_action = "show_coding_handoff_status"
        recommendation = {**recommendation, "next_action": route_next_action}
    workflow_route_plan = None
    if _operator_surface_needs_route_plan(selected_skill, extra_markers, routing_message):
        route_plan_recommendations = _operator_surface_route_plan_recommendations(
            recommendation,
            selected_skill=selected_skill,
            extra_markers=extra_markers,
            message=message,
        )
        workflow_route_plan = build_workflow_route_plan(
            message,
            route_plan_recommendations,
            selected_skill=selected_skill,
            action="dispatch",
        )
    return ChatRouteDecision(
        schema_version=1,
        source=source,
        action="dispatch",
        selected_skill=selected_skill,
        selected_harness=selected_harness,
        candidate_skill=selected_skill,
        candidate_harness=selected_harness,
        confidence="high",
        score=score,
        threshold=min_confidence,
        explicit=False,
        ambiguous=False,
        reason=why,
        clarification="",
        routing_prompt=_routing_prompt("dispatch", selected_skill, selected_skill, why, message),
        task_card=None,
        workflow_route_plan=workflow_route_plan,
        learning_candidate_card=None,
        recommendations=(recommendation,),
        route_next_action=route_next_action,
    )


def _operator_surface_fast_path_match(
    message: str,
    *,
    only_skill: str | None = None,
) -> tuple[str, str, str, str] | None:
    text = _fast_path_text(message)
    compact = _fast_path_compact(text)
    for skill, phrase, normalized_phrase, normalized_compact, marker, reason in _operator_surface_fast_path_patterns():
        if only_skill is not None and skill != only_skill:
            continue
        if normalized_phrase in text or (normalized_compact and normalized_compact in compact):
            return skill, phrase, marker, reason
    return None


def _operator_surface_guard_preempts(
    selected_skill: str,
    message: str,
    *,
    preempting_skills: tuple[str, ...],
) -> bool:
    routing_text = prepare_routing_text(message)
    normalized_query = normalized_phrase(routing_text.scoring_text)
    query_tokens = routing_tokens(normalized_query)
    for guard in active_routing_guard_rules(normalized_query, query_tokens):
        if not guard.preferred_skills:
            continue
        preferred_skill = guard.preferred_skills[0]
        if preferred_skill == selected_skill:
            return False
        if preferred_skill in preempting_skills:
            return True
    return False


@lru_cache(maxsize=1)
def _operator_surface_fast_path_patterns() -> tuple[tuple[str, str, str, str, str, str], ...]:
    patterns: list[tuple[str, str, str, str, str, str]] = []
    for skill, phrases, marker, reason in _OPERATOR_SURFACE_FAST_PATH_RULES:
        for phrase in phrases:
            normalized_phrase = _fast_path_text(phrase)
            if normalized_phrase:
                patterns.append((skill, phrase, normalized_phrase, _fast_path_compact(normalized_phrase), marker, reason))
    return tuple(patterns)


def _operator_surface_extra_markers(skill: str, phrase: str) -> tuple[str, ...]:
    normalized = _fast_path_text(phrase)
    if skill == "ultraprocess":
        if any(marker in normalized for marker in ("codex", "코덱스")):
            return ("guard:coding_handoff_status",)
        if any(marker in normalized for marker in ("friren", "프리렌", "author", "merge", "머지", "커밋")):
            return ("guard:coding_handoff_status", "guard:merge_author_constraint")
    if skill == "img-summary":
        return ("guard:img_summary",)
    if skill == "paper-learning":
        return ("guard:paper_learning",)
    if skill == "doctor":
        return ("guard:doctor_health", "guard_fast_path:doctor_health_before_skill_catalog")
    if skill == "github-event-ops":
        return ("guard:github_event_ops",)
    if skill == "memory-curation-review":
        return ("guard:memory_curation", "guard_fast_path:memory_curation_before_generic_clarification")
    if skill == "executor-runtime-readiness":
        return ("guard:executor_runtime_readiness",)
    if skill == "harness-session-inventory":
        return ("guard:harness_session_inventory",)
    if skill == "workspace-file-operator":
        return ("guard:workspace_file_operator",)
    if skill == "command-operator":
        return ("guard:command_operator",)
    if skill == "connector-operator":
        return ("guard:connector_operator",)
    if skill == "live-info-operator":
        return ("guard:live_info_operator",)
    if skill == "content-operator":
        return ("guard:content_operator",)
    if skill == "media-input-operator":
        return ("guard:media_input",)
    if skill == "data-analysis":
        return ("guard:data_analysis",)
    if skill == "context-budget-review":
        return ("guard:context_budget",)
    if skill == "agent-debug":
        return ("guard:agent_debug",)
    if skill == "instinct-ledger":
        return ("guard:instinct_ledger",)
    if skill == "skill-scout":
        return ("guard:skill_scout",)
    if skill == "skill-health":
        return ("guard:skill_health",)
    if skill != "ralplan":
        return ()
    if any(marker in normalized for marker in ("safe", "safely", "안전", "सुरक्षित")):
        markers = ["guard:safe_feature_change"]
        if "안전" in normalized:
            markers.append("locale:ko:safe_feature")
        if "सुरक्षित" in normalized:
            markers.append("locale:hi:safe_feature")
        return tuple(markers)
    if any(marker in normalized for marker in ("risk", "risky", "위험")):
        return ("guard:risky_refactor_before_cleanup",)
    return ()


def _is_installed_skill_repair_request(message: str) -> bool:
    normalized = _fast_path_text(message)
    if not any(marker in normalized for marker in ("skill", "스킬")):
        return False
    if any(
        marker in normalized
        for marker in (
            "skill-scout",
            "skill scout",
            "skill candidate",
            "skill candidates",
            "skill discovery",
            "find a skill",
            "find skills",
            "fork a skill",
            "extend a skill",
            "create skill",
            "before building",
            "before we create",
            "candidate search",
            "skill adoption",
            "스킬 후보",
            "스킬 찾기",
            "스킬 검색",
            "만들기 전",
            "만들지 결정",
        )
    ):
        return False
    repair_hit = any(
        marker in normalized
        for marker in (
            "fix",
            "repair",
            "broken",
            "broke",
            "failed",
            "failure",
            "error",
            "missing",
            "not working",
            "does not work",
            "doesn't work",
            "안 돼",
            "안돼",
            "안되",
            "고장",
            "깨",
            "실패",
            "오류",
            "수리",
            "복구",
            "문제",
        )
    )
    install_hit = any(
        marker in normalized
        for marker in (
            "install",
            "installed",
            "setup",
            "registration",
            "registered",
            "load",
            "loaded",
            "설치",
            "셋업",
            "등록",
            "로드",
        )
    )
    return repair_hit and install_hit


def _is_paper_learning_citation_research_request(message: str) -> bool:
    normalized = _fast_path_text(message)
    return (
        "citation" in normalized
        and any(marker in normalized for marker in ("verify", "validate", "check", "검증", "확인"))
    )


def _is_paper_learning_materials_request(message: str) -> bool:
    normalized = _fast_path_text(message)
    return any(
        marker in normalized
        for marker in (
            "make a ppt",
            "make a deck",
            "as a deck",
            "export a pdf",
            "export to pdf",
            "package it as a pdf",
            "ppt",
            "deck",
            "발표자료",
            "발표 자료",
        )
    )


def _is_command_operator_failure_or_coding_request(message: str) -> bool:
    normalized = _fast_path_text(message)
    return any(
        marker in normalized
        for marker in (
            "failed with",
            "failure log",
            "stack trace",
            "root cause",
            "find root cause",
            "fix the failing",
            "fix failing",
            "fix test",
            "fix tests",
            "test failed",
            "tests failed",
            "build failed",
            "ci failed",
            "lint failed",
            "typecheck failed",
            "고쳐",
            "수정",
            "실패 원인",
            "실패 로그",
            "스택 트레이스",
            "원인 찾아",
        )
    )


def _is_connector_operator_setup_or_gateway_request(message: str) -> bool:
    normalized = _fast_path_text(message)
    if any(
        marker in normalized
        for marker in (
            "connector is missing",
            "connector missing",
            "missing connector",
            "credential missing",
            "api key missing",
            "not connected",
            "not configured",
            "커넥터가 없어",
            "커넥터 없음",
        )
    ):
        return True
    return _is_gateway_delivery_policy_request(normalized)


def _is_gateway_delivery_policy_request(normalized: str) -> bool:
    platform = any(
        marker in normalized
        for marker in (
            "discord",
            "slack",
            "telegram",
            "whatsapp",
            "signal",
            "디스코드",
            "슬랙",
            "텔레그램",
        )
    )
    if not platform:
        return False
    return any(
        marker in normalized
        for marker in (
            "gateway",
            "route ",
            "routing",
            "thread",
            "delivery policy",
            "channel delivery",
            "session delivery",
            "silent",
            "silently",
            "quiet",
            "quietly",
            "status update",
            "attachment policy",
            "file attachment",
            "update the thread",
            "thread update",
            "게이트웨이",
            "라우팅",
            "스레드",
            "전달 정책",
            "조용히",
            "상태 업데이트",
            "첨부",
        )
    )


def _is_live_info_operator_setup_or_research_request(message: str) -> bool:
    normalized = _fast_path_text(message)
    return any(
        marker in normalized
        for marker in (
            "web search",
            "web research",
            "source backed",
            "with citations",
            "citations",
            "sources",
            "best practices",
            "api best practices",
            "plugin is missing",
            "plugin missing",
            "provider setup",
            "setup needed",
            "what setup",
            "connector is missing",
            "connector missing",
            "create calendar event",
            "calendar event",
            "calendar invite",
            "웹서치",
            "웹 리서치",
            "출처",
            "근거",
            "셋업",
            "설정 필요",
            "캘린더 초대",
        )
    )


def _is_content_operator_research_connector_or_materials_request(message: str) -> bool:
    normalized = _fast_path_text(message)
    return any(
        marker in normalized
        for marker in (
            "web search",
            "web research",
            "with citations",
            "citations",
            "source finder",
            "find sources",
            "find a skill",
            "find skills",
            "is there a skill",
            "skill for",
            "skill candidate",
            "skill discovery",
            "existing skill",
            "before building one",
            "before creating one",
            "ops review",
            "weekly ops review",
            "operating review",
            "customer feedback",
            "release risks",
            "image card",
            "summary card",
            "announcement card",
            "release notes image",
            "release notes card",
            "release notes thumbnail",
            "thumbnail",
            "poster",
            "visual",
            "image",
            "send email",
            "send an email",
            "send the email",
            "send slack",
            "post to slack",
            "post to discord",
            "create linear ticket",
            "export pdf",
            "export to pdf",
            "export to ppt",
            "make a ppt",
            "make slides",
            "turn into slides",
            "웹서치",
            "웹 리서치",
            "출처 찾아",
            "스킬 찾아",
            "스킬 있어",
            "스킬이 있어",
            "스킬 후보",
            "기존 스킬",
            "ops 리뷰",
            "운영 리뷰",
            "고객 피드백",
            "릴리즈 리스크",
            "이미지",
            "사진",
            "카드",
            "썸네일",
            "포스터",
            "메일 보내",
            "이메일 보내",
            "이메일 발송",
            "pdf로",
            "ppt로",
            "피피티",
            "슬라이드",
        )
    )


def _operator_surface_phrase_marker(marker: str, phrase: str) -> str:
    if marker == "operator_surface_fast_path:planning":
        normalized = _fast_path_text(phrase)
        if any(value in normalized for value in ("risk", "risky", "위험")):
            return "phrase:planning_risk"
        return "phrase:planning_safe_change"
    if marker == "operator_surface_fast_path:visual":
        return "phrase:visual_request"
    if marker == "operator_surface_fast_path:paper":
        return "phrase:paper_learning_request"
    if marker == "operator_surface_fast_path:research":
        return "phrase:web_research_request"
    if marker == "operator_surface_fast_path:source":
        return "phrase:source_request"
    if marker == "operator_surface_fast_path:delivery":
        return "phrase:delivery_request"
    if marker == "operator_surface_fast_path:doctor":
        return "phrase:doctor_health"
    if marker == "operator_surface_fast_path:github_event":
        return "phrase:github_event"
    if marker == "operator_surface_fast_path:memory":
        return "phrase:memory_curation"
    if marker == "operator_surface_fast_path:executor":
        return "phrase:executor_request"
    if marker == "operator_surface_fast_path:materials":
        return "phrase:materials_request"
    if marker == "operator_surface_fast_path:command_operator":
        return "phrase:command_operator_request"
    if marker == "operator_surface_fast_path:connector_operator":
        return "phrase:connector_operator_request"
    if marker == "operator_surface_fast_path:live_info":
        return "phrase:live_info_request"
    if marker == "operator_surface_fast_path:content_operator":
        return "phrase:content_request"
    if marker == "operator_surface_fast_path:media_input":
        return "phrase:media_input_request"
    if marker == "operator_surface_fast_path:data_analysis":
        return "phrase:data_analysis_request"
    if marker == "operator_surface_fast_path:workspace_file":
        return "phrase:workspace_file_request"
    if marker == "operator_surface_fast_path:harness_inventory":
        return "phrase:harness_inventory_request"
    if marker == "operator_surface_fast_path:automation":
        return "phrase:automation_request"
    if marker == "operator_surface_fast_path:agent_board":
        return "phrase:agent_topology_request"
    return "phrase:operator_surface"


def _operator_surface_score(skill: str, extra_markers: tuple[str, ...]) -> int:
    if skill == "ralplan" and "guard:safe_feature_change" in extra_markers:
        return 32
    if skill == "ralplan" and "guard:risky_refactor_before_cleanup" in extra_markers:
        return 32
    return 13


def _operator_surface_reason(default_reason: str, extra_markers: tuple[str, ...]) -> str:
    if "guard:safe_feature_change" in extra_markers:
        return "Matched safe feature-change language; prepare a reviewed plan before executor handoff."
    if "guard:risky_refactor_before_cleanup" in extra_markers:
        return "Matched guard/trigger metadata; risky code-change requests should get a reviewed plan before cleanup."
    return default_reason


def _operator_surface_needs_route_plan(selected_skill: str, extra_markers: tuple[str, ...], message: str) -> bool:
    if selected_skill != "ralplan":
        return False
    if "guard:safe_feature_change" in extra_markers:
        return True
    if "guard:risky_refactor_before_cleanup" in extra_markers:
        return _operator_surface_has_multi_stage_signals(message)
    return False


def _operator_surface_has_multi_stage_signals(message: str) -> bool:
    normalized = _fast_path_text(message)
    signals = (
        "implementation",
        "implement",
        "review",
        "code review",
        "docs",
        "documentation",
        "pull request",
        "research",
        "plan",
        "조사",
        "계획",
        "구현",
        "리뷰",
        "문서",
    )
    return any(signal in normalized for signal in signals) or _operator_surface_has_pr_signal(normalized)


def _operator_surface_has_pr_signal(normalized: str) -> bool:
    return bool(re.search(r"(^|[^a-z0-9])pr([^a-z0-9]|$)", normalized)) or any(
        phrase in normalized
        for phrase in (
            "pr까지",
            "pr 까지",
            "pr로",
            "pr 로",
            "pr 만들",
        )
    )


def _operator_surface_route_plan_recommendations(
    recommendation: dict[str, object],
    *,
    selected_skill: str,
    extra_markers: tuple[str, ...],
    message: str,
) -> tuple[dict[str, object], ...]:
    if selected_skill == "ralplan" and "guard:safe_feature_change" in extra_markers:
        return (
            recommendation_for_definition(
                _skill_definition_by_name("feedback-triage"),
                message,
                matched=("route_plan:triage",),
                score=5,
                why="Classify supplied feedback or bug signals before turning them into implementation work.",
            ),
            recommendation,
            recommendation_for_definition(
                _skill_definition_by_name("ultraprocess"),
                message,
                matched=("route_plan:deliver",),
                score=5,
                why="Prepare one bounded implementation or executor handoff path after planning context exists.",
            ),
        )
    return (recommendation,)


def _guarded_operator_fast_path_decision(
    message: str,
    *,
    routing_message: str,
    source: str,
    min_confidence: str,
) -> ChatRouteDecision | None:
    if _has_explicit_invocation_prefix(routing_message):
        return None
    if explicit_skill_invocation(routing_message):
        return None
    if is_skill_catalog_question(routing_message):
        return None
    if _is_fast_plain_direct_answer_question(routing_message):
        return None
    if _guarded_operator_fast_path_blocked(routing_message):
        return None
    if classify_task(message):
        return None
    routing_text = prepare_routing_text(routing_message)
    normalized_query = normalized_phrase(routing_text.scoring_text)
    query_tokens = routing_tokens(normalized_query)
    guards = active_routing_guard_rules(normalized_query, query_tokens)
    first_fast_guard_index = _first_guarded_operator_fast_path_index(guards)
    if first_fast_guard_index is None:
        return None
    if any(guard.id not in _GUARDED_OPERATOR_FAST_PATH_IDS for guard in guards[:first_fast_guard_index]):
        return None
    guard = _preferred_guarded_operator_fast_path_guard(guards, routing_message)
    if guard is None or not guard.preferred_skills:
        return None
    selected_skill = guard.preferred_skills[0]
    if selected_skill == "feedback-triage" and _feedback_triage_fast_path_blocked(routing_message):
        return None
    definition = _skill_definition_by_name(selected_skill)
    selected_harness = primary_harness_for_skill(selected_skill)
    matched = (guard.matched_label, f"guard_fast_path:{guard.id}")
    score = max(13, guard.score_boost)
    recommendation = recommendation_for_definition(
        definition,
        message,
        matched=matched,
        score=score,
        why=guard.why,
    )
    route_next_action = ""
    if guard.id in {"coding_handoff_status_before_clarify", "coding_progress_status_before_clarify"}:
        route_next_action = "show_coding_handoff_status"
        recommendation = {**recommendation, "next_action": route_next_action}
    return ChatRouteDecision(
        schema_version=1,
        source=source,
        action="dispatch",
        selected_skill=selected_skill,
        selected_harness=selected_harness,
        candidate_skill=selected_skill,
        candidate_harness=selected_harness,
        confidence="high",
        score=score,
        threshold=min_confidence,
        explicit=False,
        ambiguous=False,
        reason=guard.why,
        clarification="",
        routing_prompt=_routing_prompt("dispatch", selected_skill, selected_skill, guard.why, message),
        task_card=None,
        workflow_route_plan=None,
        learning_candidate_card=None,
        recommendations=(recommendation,),
        route_next_action=route_next_action,
    )
    return None


def _feedback_triage_fast_path_decision(
    message: str,
    *,
    routing_message: str,
    source: str,
    min_confidence: str,
) -> ChatRouteDecision | None:
    if _has_explicit_invocation_prefix(routing_message):
        return None
    if is_skill_catalog_question(routing_message):
        return None
    if _is_fast_plain_direct_answer_question(routing_message):
        return None
    fast_text = _fast_path_text(routing_message)
    if _feedback_triage_fast_path_blocked(fast_text):
        return None
    if not _feedback_triage_fast_path_signal(fast_text):
        return None

    selected_skill = "feedback-triage"
    selected_harness = primary_harness_for_skill(selected_skill)
    reason = (
        "Matched a concrete customer or product issue signal; triage the feedback before planning fixes."
    )
    score = 34
    recommendation = recommendation_for_definition(
        _skill_definition_by_name(selected_skill),
        message,
        matched=("guard:feedback_before_coding", "feedback_triage_fast_path"),
        score=score,
        why=reason,
    )
    return ChatRouteDecision(
        schema_version=1,
        source=source,
        action="dispatch",
        selected_skill=selected_skill,
        selected_harness=selected_harness,
        candidate_skill=selected_skill,
        candidate_harness=selected_harness,
        confidence="high",
        score=score,
        threshold=min_confidence,
        explicit=False,
        ambiguous=False,
        reason=reason,
        clarification="",
        routing_prompt=_routing_prompt("dispatch", selected_skill, selected_skill, reason, message),
        task_card=None,
        workflow_route_plan=None,
        learning_candidate_card=None,
        recommendations=(recommendation,),
    )


def _feedback_triage_fast_path_signal(text: str) -> bool:
    compact = _fast_path_compact(text)
    return any(term in text or _fast_path_compact(term) in compact for term in _FEEDBACK_TRIAGE_FAST_PATH_TERMS)


def _browser_visual_qa_fast_path_signal(message: str) -> bool:
    return contains_cue_phrase(message, _BROWSER_VISUAL_QA_FAST_PATH_TERMS)


def _customer_symptom_report_fast_path_signal(message: str) -> bool:
    return contains_cue_phrase(message, _CUSTOMER_SYMPTOM_REPORT_FAST_PATH_TERMS)


def _product_shaping_fast_path_decision(
    message: str,
    *,
    routing_message: str,
    source: str,
    min_confidence: str,
) -> ChatRouteDecision | None:
    if _has_explicit_invocation_prefix(routing_message):
        return None
    if is_skill_catalog_question(routing_message):
        return None
    if _is_fast_plain_direct_answer_question(routing_message):
        return None
    fast_text = _fast_path_text(routing_message)
    if _product_shaping_fast_path_blocked(fast_text):
        return None
    if not _product_shaping_fast_path_signal(fast_text):
        return None

    selected_skill = "deep-interview"
    selected_harness = primary_harness_for_skill(selected_skill)
    reason = "Matched fuzzy product-shaping language; ask one clarifying question before planning or execution."
    score = 30
    recommendation = recommendation_for_definition(
        _skill_definition_by_name(selected_skill),
        message,
        matched=("guard:product_shaping", "product_shaping_fast_path"),
        score=score,
        why=reason,
    )
    return ChatRouteDecision(
        schema_version=1,
        source=source,
        action="dispatch",
        selected_skill=selected_skill,
        selected_harness=selected_harness,
        candidate_skill=selected_skill,
        candidate_harness=selected_harness,
        confidence="high",
        score=score,
        threshold=min_confidence,
        explicit=False,
        ambiguous=False,
        reason=reason,
        clarification="",
        routing_prompt=_routing_prompt("dispatch", selected_skill, selected_skill, reason, message),
        task_card=None,
        workflow_route_plan=None,
        learning_candidate_card=None,
        recommendations=(recommendation,),
    )


def _product_shaping_fast_path_signal(text: str) -> bool:
    compact = _fast_path_compact(text)
    return any(term in text or _fast_path_compact(term) in compact for term in _PRODUCT_SHAPING_FAST_PATH_TERMS)


def _workflow_learning_feedback_fast_path_decision(
    message: str,
    *,
    routing_message: str,
    source: str,
    min_confidence: str,
) -> ChatRouteDecision | None:
    if _has_explicit_invocation_prefix(routing_message):
        return None
    if is_skill_catalog_question(routing_message):
        return None
    if _is_fast_plain_direct_answer_question(routing_message):
        return None
    fast_text = _fast_path_text(routing_message)
    if any(blocker in fast_text for blocker in _LEARNING_CANDIDATE_FAST_PATH_BLOCKERS):
        return None
    if not _workflow_learning_fast_path_signal(fast_text):
        return None

    selected_skill = "workflow-learning"
    selected_harness = primary_harness_for_skill(selected_skill)
    route_next_action = _workflow_learning_fast_path_next_action(routing_message)
    task_card = classify_task(routing_message)
    short_feedback = len(fast_text) <= 240
    if (
        isinstance(task_card, dict)
        and task_card.get("selected_workflow_rail") == selected_skill
    ):
        if not short_feedback:
            return None
        recommendation = _task_card_fast_path_recommendation(task_card, message)
        reason = str(task_card.get("routing_reason", recommendation.get("why", "")))
        score = _int_value(task_card.get("score", recommendation.get("score", 12)))
        confidence = str(task_card.get("confidence", recommendation.get("confidence", "high")))
        route_next_action = str(task_card.get("recommended_next_action", route_next_action))
    else:
        if not short_feedback:
            return None
        reason = (
            "Matched workflow-learning feedback language; prepare a learning trace, review candidate, "
            "or regression case without scanning every workflow definition."
        )
        score = 34
        confidence = "high"
        recommendation = recommendation_for_definition(
            _skill_definition_by_name(selected_skill),
            message,
            matched=("guard:workflow_learning", "workflow_learning_fast_path"),
            score=score,
            why=reason,
        )
        if route_next_action and route_next_action != str(recommendation.get("next_action", "")):
            recommendation = {**recommendation, "next_action": route_next_action}
        task_card = None

    return ChatRouteDecision(
        schema_version=1,
        source=source,
        action="dispatch",
        selected_skill=selected_skill,
        selected_harness=selected_harness,
        candidate_skill=selected_skill,
        candidate_harness=selected_harness,
        confidence=confidence,
        score=score,
        threshold=min_confidence,
        explicit=False,
        ambiguous=False,
        reason=reason,
        clarification="",
        routing_prompt=_routing_prompt("dispatch", selected_skill, selected_skill, reason, message),
        task_card=task_card,
        workflow_route_plan=None,
        learning_candidate_card=None,
        recommendations=(recommendation,),
        route_next_action=route_next_action,
    )


def _workflow_learning_fast_path_signal(text: str) -> bool:
    compact = _fast_path_compact(text)
    if not text:
        return False
    has_learning_subject = any(
        term in text or _fast_path_compact(term) in compact for term in _WORKFLOW_LEARNING_FAST_PATH_TERMS
    )
    if not has_learning_subject:
        return False
    return any(
        term in text or _fast_path_compact(term) in compact for term in _WORKFLOW_LEARNING_FAST_PATH_ACTION_TERMS
    )


def _workflow_learning_fast_path_next_action(message: str) -> str:
    return "record_missed_route" if is_missed_route_feedback(message) else "audit_learning_readiness"


def _preferred_guarded_operator_fast_path_guard(guards: tuple[Any, ...], message: str) -> Any | None:
    guard_by_id = {guard.id: guard for guard in guards if guard.id in _GUARDED_OPERATOR_FAST_PATH_IDS}
    handoff_guard = guard_by_id.get("coding_handoff_status_before_clarify")
    progress_guard = guard_by_id.get("coding_progress_status_before_clarify")
    if handoff_guard is not None and progress_guard is not None and _guarded_operator_handoff_status_request(message):
        return handoff_guard
    for guard in guards:
        if guard.id in _GUARDED_OPERATOR_FAST_PATH_IDS and guard.preferred_skills:
            return guard
    for guard_id in _GUARDED_OPERATOR_FAST_PATH_PRIORITY:
        guard = guard_by_id.get(guard_id)
        if guard is not None and guard.preferred_skills:
            return guard
    return None


def _guarded_operator_handoff_status_request(message: str) -> bool:
    text = _fast_path_text(message)
    if "handoff" not in text and "위임" not in text:
        return False
    status_markers = (
        "status",
        "progress",
        "current",
        "what did",
        "do so far",
        "evidence",
        "done",
        "상태",
        "진행",
        "어디까지",
        "근거",
        "증거",
        "완료",
    )
    return any(marker in text for marker in status_markers)


def _guarded_operator_fast_path_blocked(message: str) -> bool:
    text = _fast_path_text(message)
    if any(blocker in text for blocker in _GUARDED_OPERATOR_META_BLOCKERS):
        return True
    return any(blocker in text for blocker in _LEARNING_CANDIDATE_FAST_PATH_BLOCKERS)


def _feedback_triage_fast_path_blocked(message: str) -> bool:
    text = _fast_path_text(message)
    compact = _fast_path_compact(text)
    return any(blocker in text or _fast_path_compact(blocker) in compact for blocker in _FEEDBACK_TRIAGE_FAST_PATH_BLOCKERS)


def _product_shaping_fast_path_blocked(message: str) -> bool:
    text = _fast_path_text(message)
    compact = _fast_path_compact(text)
    return any(blocker in text or _fast_path_compact(blocker) in compact for blocker in _PRODUCT_SHAPING_FAST_PATH_BLOCKERS)


def _first_guarded_operator_fast_path_index(guards: tuple[Any, ...]) -> int | None:
    for index, guard in enumerate(guards):
        if getattr(guard, "id", "") in _GUARDED_OPERATOR_FAST_PATH_IDS:
            return index
    return None


def _fast_path_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", value).strip().lower().strip(" \t\r\n.!?,;:~…？"))


def _fast_path_compact(value: str) -> str:
    return re.sub(r"[\s\?\!\.,;:~…？]+", "", value)


def _direct_answer_fast_path_decision(
    message: str,
    *,
    routing_message: str,
    source: str,
    min_confidence: str,
) -> ChatRouteDecision | None:
    if _has_explicit_invocation_prefix(routing_message):
        return None
    if not _is_fast_plain_direct_answer_question(routing_message):
        return None
    selected_harness = primary_harness_for_skill(_ROUTER_SKILL)
    reason = DIRECT_ANSWER_REASON
    return ChatRouteDecision(
        schema_version=1,
        source=source,
        action="fallback",
        selected_skill=_ROUTER_SKILL,
        selected_harness=selected_harness,
        candidate_skill=_ROUTER_SKILL,
        candidate_harness=selected_harness,
        confidence="low",
        score=0,
        threshold=min_confidence,
        explicit=False,
        ambiguous=False,
        reason=reason,
        clarification=_clarification("fallback", _ROUTER_SKILL, "low", min_confidence, reason),
        routing_prompt=_routing_prompt("fallback", _ROUTER_SKILL, _ROUTER_SKILL, reason, message),
        task_card=None,
        workflow_route_plan=None,
        learning_candidate_card=None,
        recommendations=(_router_direct_answer_recommendation(message),),
    )


def _router_direct_answer_recommendation(query: str) -> dict[str, object]:
    definition = _router_skill_definition()
    return {
        "skill": definition.name,
        "description": definition.description,
        "category": definition.category,
        "phase": definition.phase,
        "hermes_role": definition.hermes_role,
        "handoff_policy": definition.handoff_policy,
        "score": 0,
        "confidence": "low",
        "matched": ["direct_answer_fast_path"],
        "why": DIRECT_ANSWER_REASON,
        "next_action": "answer_directly",
        "evidence_boundary": "No OMH workflow, picker, handoff, execution, or file inspection has started.",
        "wrapper_guidance": "Answer in the current chat; do not open an OMH workflow, picker, or coding handoff.",
        "suggested_prompt": query,
    }


def _generic_omh_catalog_question(message: str) -> bool:
    text = message.strip().lower()
    if is_native_entrypoint_question(message):
        return True
    if _is_broad_capability_catalog_question(text):
        return True
    has_omh_context = any(marker in text for marker in ("omh", "oh-my-hermes", "oh my hermes"))
    if not has_omh_context:
        return _generic_catalog_listing_question(text)
    if any(marker in text for marker in ("picker", "menu", "workflow picker", "skill picker")):
        return True
    named_hits = len(_specific_capability_named_hits(text))
    if named_hits:
        return False
    if any(phrase in text for phrase in _SPECIFIC_CAPABILITY_ALIAS_PHRASES):
        return False
    if _is_specific_capability_question_shape(text):
        return False
    if any(marker in text for marker in _GENERIC_OMH_CAPABILITY_LISTING_MARKERS):
        return True
    return _generic_catalog_listing_question(text)


def _generic_catalog_listing_question(text: str) -> bool:
    has_collection = any(marker in text for marker in _GENERIC_PICKER_COLLECTION_MARKERS)
    has_listing_intent = any(marker in text for marker in _GENERIC_CATALOG_LISTING_MARKERS)
    return has_collection and has_listing_intent


def _is_specific_capability_question_shape(text: str) -> bool:
    text = text.strip().lower()
    return any(
        marker in text
        for marker in (
            "what can omh do for ",
            "what can oh-my-hermes do for ",
            "can omh help with ",
            "can oh-my-hermes help with ",
            "does omh support ",
            "does oh-my-hermes support ",
        )
    )


def _native_entrypoint_next_action(message: str) -> str:
    normalized = unicodedata.normalize("NFKC", message).casefold()
    if any(marker in normalized for marker in ("./", "preview", "autocomplete", "미리보기", "자동완성", "안 떠", "안떠", "안 보", "안보")):
        return "show_command_preview"
    return "choose_skill"


def _router_picker_recommendation(
    query: str,
    *,
    matched: tuple[str, ...],
    score: int,
    next_action: str = "choose_skill",
) -> dict[str, object]:
    definition = _router_skill_definition()
    wrapper_guidance = (
        "Render the OMH command preview or fallback Open omh card in chat; do not ask the user to approve `omh list` for catalog discovery."
        if next_action == "show_command_preview"
        else "Render the OMH workflow picker in chat; do not ask the user to approve `omh list` for catalog discovery."
    )
    return {
        "skill": definition.name,
        "description": definition.description,
        "category": definition.category,
        "phase": definition.phase,
        "hermes_role": definition.hermes_role,
        "handoff_policy": definition.handoff_policy,
        "score": score,
        "confidence": "high",
        "matched": list(matched),
        "why": "Matched the OMH workflow picker entry point.",
        "next_action": next_action,
        "evidence_boundary": (
            "Skill picker routing is not plan acceptance, dispatch, execution, review, CI, or verification evidence."
        ),
        "wrapper_guidance": wrapper_guidance,
        "suggested_prompt": f"Use oh-my-hermes for: {query}",
    }


@lru_cache(maxsize=1)
def _router_skill_definition() -> SkillDefinition:
    return _skill_definition_by_name(_ROUTER_SKILL)


@lru_cache(maxsize=128)
def _skill_definition_by_name(name: str) -> SkillDefinition:
    for definition in routable_definitions():
        if definition.name == name:
            return definition
    raise RuntimeError(f"{name} skill definition is missing")


def _task_card_overrides_explicit_invocation(
    task_card: dict[str, object] | None,
    *,
    explicit_prefix: bool,
) -> bool:
    if not isinstance(task_card, dict):
        return False
    task_type = task_card.get("task_type")
    if task_type == "omh_cli_maintenance":
        return True
    if task_type == "router_design_feedback":
        return not explicit_prefix
    return False


def route_chat_event(
    event: dict[str, Any] | str,
    *,
    source: str = "generic",
    limit: int = 3,
    min_confidence: str = "high",
) -> dict[str, object]:
    return route_chat_message(extract_message_text(event), source=source, limit=limit, min_confidence=min_confidence)


def public_route_payload(decision: dict[str, object], *, include_message: bool = False) -> dict[str, object]:
    route = dict(decision)
    route["recommendations"] = _compact_recommendations(route.get("recommendations", []))
    route["routing_instruction"] = _routing_instruction(
        str(route["action"]),
        str(route["selected_skill"]),
        str(route["candidate_skill"]),
        str(route["reason"]),
    )
    route["routing_prompt_template"] = _routing_prompt_template(
        str(route["action"]),
        str(route["selected_skill"]),
        str(route["candidate_skill"]),
        str(route["reason"]),
    )
    if not include_message:
        route.pop("routing_prompt", None)
    if not route.get("task_card"):
        route.pop("task_card", None)
    if not route.get("learning_candidate_card"):
        route.pop("learning_candidate_card", None)
    workflow_route_plan = compact_workflow_route_plan(route.get("workflow_route_plan"))
    if workflow_route_plan:
        route["workflow_route_plan"] = workflow_route_plan
    else:
        route.pop("workflow_route_plan", None)
    route["route_explanation"] = route_explanation_payload(route)
    return route


def route_explanation_payload(route: dict[str, object]) -> dict[str, object]:
    """Build a compact human-facing explanation without storing the raw message."""
    action = str(route.get("action", "fallback"))
    selected = str(route.get("selected_skill", ""))
    harness = str(route.get("selected_harness", "")) or primary_harness_for_skill(selected)
    recommendation = _selected_recommendation(route)
    next_action = _route_next_action(route, recommendation)
    claim_boundary = _route_claim_boundary(route, recommendation)
    why = _route_explanation_reason(route)
    not_evidence_yet = _not_evidence_from_boundary(claim_boundary)
    headline = _route_explanation_headline(action, selected, next_action)
    next_action_label = _route_next_action_label(next_action)
    summary = _route_explanation_summary(action, selected, next_action, next_action_label, why)
    return {
        "schema_version": ROUTE_EXPLANATION_SCHEMA_VERSION,
        "selected_workflow": selected,
        "selected_harness": harness,
        "action": action,
        "confidence": str(route.get("confidence", "low")),
        "score": _int_value(route.get("score", 0)),
        "why_this_workflow": why,
        "next_action": next_action,
        "next_action_label": next_action_label,
        "recommended_reply": _route_recommended_reply(action, selected, next_action, next_action_label, not_evidence_yet),
        "primary_action_label": _route_primary_action_label(action, selected, next_action),
        "primary_action_hint": _route_primary_action_hint(
            action,
            selected,
            next_action,
            next_action_label,
            not_evidence_yet,
        ),
        "not_evidence_yet": not_evidence_yet,
        "claim_boundary": claim_boundary,
        "headline": headline,
        "summary": summary,
        "rendering_hint": "Show this as the compact why / next / not-yet-evidence card in chat surfaces.",
    }


def explicit_skill_invocation(message: str, definitions: list[SkillDefinition] | None = None) -> str | None:
    definitions = definitions or routable_definitions()
    return explicit_skill_name(message, {definition.name for definition in definitions})


def _explicit_loop_signal(message: str, recommendations: list[dict[str, object]]) -> bool:
    has_loop_recommendation = any(str(item.get("skill", "")) == "loop" for item in recommendations[:3])
    if not has_loop_recommendation:
        return False
    return explicit_loop_invocation_signal(message)


def _route_specific_next_action(message: str, *, selected_skill: str, explicit_loop: bool) -> str:
    if selected_skill != "loop":
        return ""
    return _loop_route_next_action(message, explicit_loop=explicit_loop)


def _loop_route_next_action(message: str, *, explicit_loop: bool) -> str:
    try:
        assessment = assess_loopability(message, expose_goal=False)
    except ValueError:
        return "ask_goal_boundary" if explicit_loop else ""
    loopability = str(assessment.get("loopability", ""))
    recommended_next_action = str(assessment.get("recommended_next_action", "")).strip()
    if explicit_loop:
        if loopability == "needs_clarification":
            return recommended_next_action or "ask_goal_boundary"
        if loopability == "direct_task":
            return "route_direct_task"
        if loopability == "external_wait_only":
            return "record_external_wait"
        return "start_loop_cycle"
    return recommended_next_action


def routing_record_payload(
    decision: dict[str, object],
    message: str,
    *,
    source_event_id: str = "",
    channel_ref: str = "",
    user_ref: str = "",
) -> dict[str, object]:
    payload = {
        "source": decision["source"],
        "action": decision["action"],
        "selected_skill": decision["selected_skill"],
        "selected_harness": decision["selected_harness"],
        "candidate_skill": decision["candidate_skill"],
        "candidate_harness": decision["candidate_harness"],
        "confidence": decision["confidence"],
        "score": decision["score"],
        "threshold": decision["threshold"],
        "explicit": decision["explicit"],
        "ambiguous": decision["ambiguous"],
        "reason": decision["reason"],
        "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
        "message_length": len(message),
        "source_event_id": source_event_id,
        "channel_ref": channel_ref,
        "user_ref": user_ref,
        "recommendations": _compact_recommendations(decision.get("recommendations", [])),
    }
    workflow_route_plan = compact_workflow_route_plan(decision.get("workflow_route_plan"))
    if workflow_route_plan:
        payload["workflow_route_plan"] = workflow_route_plan
    task_card = decision.get("task_card")
    if isinstance(task_card, dict) and task_card:
        payload["task_card"] = task_card
    learning_candidate_card = decision.get("learning_candidate_card")
    if isinstance(learning_candidate_card, dict) and learning_candidate_card:
        payload["learning_candidate_card"] = learning_candidate_card
    return payload


def _is_ambiguous(recommendations: list[dict[str, object]]) -> bool:
    if len(recommendations) < 2:
        return False
    first = _int_value(recommendations[0]["score"])
    second = _int_value(recommendations[1]["score"])
    return is_ambiguous_scores(first, second)


def _meets_threshold(confidence: str, threshold: str) -> bool:
    return meets_confidence_threshold(confidence, threshold)


def _specific_capability_catalog_match(
    recommendations: list[dict[str, object]],
    message: str,
) -> dict[str, object] | None:
    named_hits = set(_specific_capability_named_hits(message))
    for recommendation in recommendations:
        skill = str(recommendation.get("skill", ""))
        if skill not in named_hits:
            continue
        if not _is_eligible_specific_capability_recommendation(recommendation):
            continue
        return recommendation

    for recommendation in recommendations:
        skill = str(recommendation.get("skill", ""))
        if skill not in _specific_capability_catalog_skills():
            continue
        if not _is_eligible_specific_capability_recommendation(recommendation):
            continue
        matched = _string_list(recommendation.get("matched", []))
        if any(item.startswith("guard:") for item in matched) or any(item.startswith("trigger:") for item in matched):
            return recommendation
    return None


def _is_eligible_specific_capability_recommendation(recommendation: dict[str, object]) -> bool:
    if _int_value(recommendation.get("score", 0)) < _SPECIFIC_CAPABILITY_CATALOG_MIN_SCORE:
        return False
    confidence = str(recommendation.get("confidence", "low"))
    if not _meets_threshold(confidence, "high"):
        return False
    next_action = str(recommendation.get("next_action", ""))
    return bool(next_action and next_action != "clarify_or_route")


@lru_cache(maxsize=2048)
def _is_broad_capability_catalog_question(message: str) -> bool:
    text = message.strip().lower()
    if any(phrase in text for phrase in _BROAD_CAPABILITY_CATALOG_PHRASES):
        return True
    if "/" in text or "," in text:
        topic_hits = sum(1 for token in _BROAD_CAPABILITY_TOPIC_TOKENS if token in text)
        if topic_hits >= 2:
            return True
    named_hits = len(_specific_capability_named_hits(text))
    return named_hits >= 2


@lru_cache(maxsize=1)
def _specific_capability_catalog_skills() -> frozenset[str]:
    return frozenset(
        definition.name
        for definition in routable_definitions()
        if definition.name not in _SPECIFIC_CAPABILITY_EXCLUDED_SKILLS
    )


@lru_cache(maxsize=1)
def _specific_capability_phrase_map() -> tuple[_SpecificCapabilityPhrase, ...]:
    entries: list[_SpecificCapabilityPhrase] = []
    for skill in sorted(_specific_capability_catalog_skills()):
        variants = {
            skill,
            skill.replace("-", " "),
            skill.replace("-", "_"),
        }
        for phrase in sorted(variants):
            entries.append(
                _SpecificCapabilityPhrase(
                    skill=skill,
                    phrase=phrase,
                    pattern=_compile_specific_capability_phrase(phrase),
                )
            )
    return tuple(entries)


@lru_cache(maxsize=2048)
def _specific_capability_named_hits(message: str) -> tuple[str, ...]:
    text = message.strip().lower()
    matches: list[tuple[int, int, int, str]] = []
    for phrase in _specific_capability_phrase_map():
        for start, end in _specific_capability_phrase_matches(text, phrase):
            matches.append((start, end, len(phrase.phrase), phrase.skill))

    selected: list[str] = []
    selected_ranges: list[tuple[int, int]] = []
    for start, end, _length, skill in sorted(matches, key=lambda item: (-(item[1] - item[0]), item[0], item[3])):
        if any(start < selected_end and end > selected_start for selected_start, selected_end in selected_ranges):
            continue
        if skill not in selected:
            selected.append(skill)
        selected_ranges.append((start, end))
    return tuple(selected)


@lru_cache(maxsize=2048)
def _specific_capability_alias_hit(message: str) -> tuple[str, str]:
    text = message.strip().lower()
    if not _is_specific_capability_question_shape(text):
        return ("", "")
    named_hits = _specific_capability_named_hits(text)
    if len(named_hits) == 1:
        return (named_hits[0], named_hits[0])

    hits: list[tuple[int, int, int, str, str]] = []
    for phrase in _specific_capability_alias_phrase_map():
        for start, end in _specific_capability_phrase_matches(text, phrase):
            hits.append((start, end, len(phrase.phrase), phrase.skill, phrase.phrase))
    if not hits:
        return ("", "")

    ordered = sorted(hits, key=lambda item: (-(item[2]), item[0], item[3]))
    first_skill = ordered[0][3]
    first_alias = ordered[0][4]
    if any(
        skill != first_skill and start == ordered[0][0] and end == ordered[0][1]
        for start, end, _size, skill, _alias in ordered[1:]
    ):
        return ("", "")
    return (first_skill, first_alias)


@lru_cache(maxsize=1)
def _specific_capability_alias_phrase_map() -> tuple[_SpecificCapabilityPhrase, ...]:
    entries: list[_SpecificCapabilityPhrase] = []
    for skill, aliases in _SPECIFIC_CAPABILITY_FAST_ALIASES:
        for alias in aliases:
            entries.append(
                _SpecificCapabilityPhrase(
                    skill=skill,
                    phrase=alias,
                    pattern=_compile_specific_capability_phrase(alias),
                )
            )
    return tuple(entries)


@lru_cache(maxsize=2048)
def _specific_capability_exact_id_hit(message: str) -> str | None:
    text = message.strip().lower()
    hits: list[str] = []
    for phrase in _specific_capability_phrase_map():
        if "-" not in phrase.phrase and "_" not in phrase.phrase:
            continue
        if phrase.phrase not in (phrase.skill, phrase.skill.replace("-", "_")):
            continue
        if not _specific_capability_phrase_matches(text, phrase):
            continue
        if phrase.skill not in hits:
            hits.append(phrase.skill)
    return hits[0] if len(hits) == 1 else None


def _compile_specific_capability_phrase(phrase: str) -> re.Pattern[str]:
    boundary = r"(?<![a-z0-9_])"
    end_boundary = r"(?![a-z0-9_])"
    return re.compile(f"{boundary}{re.escape(phrase)}{end_boundary}")


def _specific_capability_phrase_matches(
    text: str,
    phrase: _SpecificCapabilityPhrase,
) -> tuple[tuple[int, int], ...]:
    if not phrase.phrase:
        return ()
    return tuple((match.start(), match.end()) for match in phrase.pattern.finditer(text))


def _prioritize_recommendation(
    recommendations: list[dict[str, object]],
    selected: dict[str, object],
) -> list[dict[str, object]]:
    selected_skill = str(selected.get("skill", ""))
    return [selected] + [item for item in recommendations if str(item.get("skill", "")) != selected_skill]


def _recommendation_for_skill(
    recommendations: list[dict[str, object]],
    skill: str,
) -> dict[str, object] | None:
    for item in recommendations:
        if str(item.get("skill", "")) == skill:
            return item
    return None


def _clarification(action: str, candidate_skill: str, candidate_confidence: str, threshold: str, reason: str = "") -> str:
    if action == "dispatch":
        return ""
    if action == "fallback":
        if _is_file_lookup_reason(reason):
            return "Answer this as a file or text lookup, or ask for the target file/path if it is missing."
        if _is_direct_answer_reason(reason):
            return "Answer directly in the current chat; do not open an OMH workflow unless the user asks for one."
        return "Ask which workflow or outcome the user wants before choosing a specialist skill."
    return f"Ask whether to use `{candidate_skill}`; confidence was {candidate_confidence}, below threshold {threshold}."


def _routing_prompt(action: str, selected_skill: str, candidate_skill: str, reason: str, message: str) -> str:
    return _routing_prompt_template(action, selected_skill, candidate_skill, reason).replace("{message}", message)


def _routing_prompt_template(action: str, selected_skill: str, candidate_skill: str, reason: str) -> str:
    return f"{_routing_instruction(action, selected_skill, candidate_skill, reason)}\n\nRouting reason: {reason}\n\nUser message:\n{{message}}"


def _routing_instruction(action: str, selected_skill: str, candidate_skill: str, reason: str = "") -> str:
    if action == "dispatch":
        return f"Use the `{selected_skill}` workflow for this chat message."
    elif action == "clarify":
        return f"Use the `oh-my-hermes` router before dispatching to `{candidate_skill}`."
    if _is_file_lookup_reason(reason):
        return "Answer this as a file or text lookup; do not dispatch to a workflow keyword unless the user explicitly asks."
    if _is_direct_answer_reason(reason):
        return "Answer directly in chat; do not open an OMH workflow, picker, or coding handoff."
    return "Use the `oh-my-hermes` router and ask one concise clarification question."


def _is_file_lookup_reason(reason: str) -> bool:
    return reason == FILE_LOOKUP_REASON


def _is_direct_answer_reason(reason: str) -> bool:
    return reason == DIRECT_ANSWER_REASON


def _is_plain_direct_answer_question(message: str, *, candidate_score: int) -> bool:
    if candidate_score > 4:
        return False
    text = message.strip().lower()
    if not text:
        return False
    direct_text = _strip_direct_answer_soft_prefix(text)
    if _is_plain_setup_how_to_question(direct_text):
        return True
    if _is_plain_conversational_turn(direct_text):
        return True
    if _is_direct_answer_concept_question(text, direct_text):
        return True
    if _is_plain_text_transform_question(text, direct_text):
        return True
    if _is_plain_error_or_log_help_question(text, direct_text):
        return True
    if _contains_direct_answer_blocker(text) or _contains_direct_answer_blocker(direct_text):
        return False
    if any(direct_text.startswith(starter) for starter in _DIRECT_ANSWER_STARTERS):
        return True
    return any(keyword in direct_text for keyword in _DIRECT_ANSWER_KEYWORDS) and "?" in text


def _is_fast_plain_direct_answer_question(message: str) -> bool:
    text = message.strip().lower()
    if not text:
        return False
    direct_text = _strip_direct_answer_soft_prefix(text)
    if _is_plain_setup_how_to_question(direct_text):
        return True
    if _is_plain_conversational_turn(direct_text):
        return True
    if _is_direct_answer_concept_question(text, direct_text):
        return True
    if _is_plain_text_transform_question(text, direct_text):
        return True
    if _is_plain_error_or_log_help_question(text, direct_text):
        return True
    if _contains_direct_answer_blocker(text) or _contains_direct_answer_blocker(direct_text):
        return False
    if not any(
        direct_text.startswith(starter)
        for starter in (
            "please explain",
            "explain ",
            "describe ",
            "tell me ",
        )
    ):
        return False
    keywords = _DIRECT_ANSWER_KEYWORDS + _DIRECT_ANSWER_SETUP_KEYWORDS
    return any(keyword in direct_text for keyword in keywords)


def _strip_direct_answer_soft_prefix(text: str) -> str:
    for prefix in _DIRECT_ANSWER_SOFT_PREFIXES:
        if text.startswith(prefix):
            return text[len(prefix) :].lstrip()
    return text


def _is_plain_setup_how_to_question(text: str) -> bool:
    if not any(text.startswith(starter) for starter in _DIRECT_ANSWER_HOW_TO_STARTERS):
        return False
    if _contains_marker(text, _DIRECT_ANSWER_HARD_BLOCKERS):
        return False
    return any(keyword in text for keyword in _DIRECT_ANSWER_SETUP_KEYWORDS)


def _is_plain_conversational_turn(text: str) -> bool:
    compact = text.strip(" \t\r\n.!?。！？")
    return compact in _DIRECT_ANSWER_ACKNOWLEDGEMENTS or text in _DIRECT_ANSWER_CONTEXT_QUESTIONS


def _is_plain_error_or_log_help_question(text: str, direct_text: str) -> bool:
    if _contains_marker(text, _DIRECT_ANSWER_ERROR_HELP_HARD_BLOCKERS) or _contains_marker(
        direct_text,
        _DIRECT_ANSWER_ERROR_HELP_HARD_BLOCKERS,
    ):
        return False
    if any(direct_text.startswith(starter) for starter in _DIRECT_ANSWER_ERROR_HELP_STARTERS):
        return True
    if any(subject in direct_text for subject in _DIRECT_ANSWER_KOREAN_ERROR_HELP_SUBJECTS):
        return any(action in direct_text for action in _DIRECT_ANSWER_KOREAN_ERROR_HELP_ACTIONS)
    return False


def _is_plain_text_transform_question(text: str, direct_text: str) -> bool:
    if _is_single_word_translation_request(direct_text):
        return True
    if _contains_marker(text, _DIRECT_ANSWER_TEXT_TRANSFORM_HARD_BLOCKERS) or _contains_marker(
        direct_text,
        _DIRECT_ANSWER_TEXT_TRANSFORM_HARD_BLOCKERS,
    ):
        return False
    if any(direct_text.startswith(starter) for starter in _DIRECT_ANSWER_TEXT_TRANSFORM_STARTERS):
        return True
    if any(subject in direct_text for subject in _DIRECT_ANSWER_KOREAN_TEXT_TRANSFORM_SUBJECTS):
        return any(action in direct_text for action in _DIRECT_ANSWER_KOREAN_TEXT_TRANSFORM_ACTIONS)
    return False


def _is_single_word_translation_request(direct_text: str) -> bool:
    if not any(marker in direct_text for marker in ("라는 단어", "라는 말")):
        return False
    return any(action in direct_text for action in ("번역", "한국어로", "영어로"))


def _is_direct_answer_concept_question(text: str, direct_text: str) -> bool:
    if _is_blocked_term_definition_question(direct_text):
        return True
    if _contains_marker(text, _DIRECT_ANSWER_CONCEPT_HARD_BLOCKERS) or _contains_marker(
        direct_text, _DIRECT_ANSWER_CONCEPT_HARD_BLOCKERS
    ):
        return False
    stripped = direct_text.strip(" \t\r\n.!?¿¡。！？")
    if any(stripped.startswith(marker) for marker in _DIRECT_ANSWER_MULTILINGUAL_CONTEXT_QUESTIONS):
        return False
    if _is_what_means_concept_question(direct_text):
        return True
    has_concept_keyword = _contains_concept_keyword(direct_text)
    if any(direct_text.startswith(starter) for starter in _DIRECT_ANSWER_CONCEPT_STARTERS):
        return has_concept_keyword or _is_short_generic_concept_question(direct_text)
    if any(direct_text.startswith(starter) for starter in _DIRECT_ANSWER_MULTILINGUAL_CONCEPT_STARTERS):
        return _is_short_generic_multilingual_concept_question(direct_text)
    if any(marker in direct_text for marker in _DIRECT_ANSWER_KOREAN_CONCEPT_MARKERS):
        return has_concept_keyword or _is_short_generic_korean_concept_question(direct_text)
    if any(marker in direct_text for marker in _DIRECT_ANSWER_MULTILINGUAL_CONCEPT_MARKERS):
        return _is_short_generic_multilingual_concept_question(direct_text)
    if has_concept_keyword and any(
        direct_text.startswith(starter) for starter in _DIRECT_ANSWER_CONCEPT_EXPLAIN_STARTERS
    ):
        return True
    if any(direct_text.startswith(starter) for starter in _DIRECT_ANSWER_MULTILINGUAL_EXPLAIN_STARTERS):
        return _is_short_generic_multilingual_concept_question(direct_text)
    if any(marker in direct_text for marker in _DIRECT_ANSWER_KOREAN_EXPLAIN_MARKERS):
        return has_concept_keyword or _is_short_generic_korean_concept_question(direct_text)
    if any(marker in direct_text for marker in _DIRECT_ANSWER_MULTILINGUAL_EXPLAIN_MARKERS):
        return _is_short_generic_multilingual_concept_question(direct_text)
    return False


def _is_blocked_term_definition_question(text: str) -> bool:
    tail = ""
    stripped = text.strip(" \t\r\n.!?¿¡。！？")
    for starter in _DIRECT_ANSWER_CONCEPT_STARTERS:
        if stripped.startswith(starter):
            tail = stripped[len(starter) :]
            break
    if not tail:
        return False
    tail = re.sub(r"^(?:a|an|the)\s+", "", tail.strip(" \t\r\n.!?¿¡。！？"))
    tail = re.sub(r"\s+(?:in simple terms|simply|exactly)$", "", tail).strip()
    return tail in _DIRECT_ANSWER_BLOCKED_TERM_CONCEPTS


def _is_what_means_concept_question(text: str) -> bool:
    stripped = text.strip(" \t\r\n.!?¿¡。！？")
    if not stripped.startswith("what "):
        return False
    for suffix in (" means", " mean"):
        if stripped.endswith(suffix):
            subject = stripped[len("what ") : -len(suffix)].strip(" \t\r\n.!?¿¡。！？")
            if not subject:
                return False
            words = _word_tokens(subject)
            return 1 <= len(words) <= _DIRECT_ANSWER_GENERIC_CONCEPT_MAX_WORDS
    return False


def _is_short_generic_concept_question(text: str) -> bool:
    tail = text
    for starter in _DIRECT_ANSWER_CONCEPT_STARTERS:
        if text.startswith(starter):
            tail = text[len(starter) :]
            break
    tail = tail.strip(" \t\r\n.!?")
    if not tail:
        return False
    words = _word_tokens(tail)
    return 1 <= len(words) <= _DIRECT_ANSWER_GENERIC_CONCEPT_MAX_WORDS


def _is_short_generic_korean_concept_question(text: str) -> bool:
    compact = text.strip(" \t\r\n.!?")
    if not compact:
        return False
    if not any("\uac00" <= character <= "\ud7a3" for character in compact):
        return False
    return len(compact) <= _DIRECT_ANSWER_GENERIC_KOREAN_CONCEPT_MAX_CHARS


def _is_short_generic_multilingual_concept_question(text: str) -> bool:
    compact = text.strip(" \t\r\n.!?¿¡。！？")
    if not compact:
        return False
    for starter in _DIRECT_ANSWER_MULTILINGUAL_CONCEPT_STARTERS + _DIRECT_ANSWER_MULTILINGUAL_EXPLAIN_STARTERS:
        if compact.startswith(starter):
            compact = compact[len(starter) :].strip(" \t\r\n.!?¿¡。！？")
            break
    for marker in _DIRECT_ANSWER_MULTILINGUAL_CONCEPT_MARKERS + _DIRECT_ANSWER_MULTILINGUAL_EXPLAIN_MARKERS:
        compact = compact.replace(marker, "")
    compact = compact.strip(" \t\r\n.!?¿¡。！？")
    if not compact:
        return False
    words = _word_tokens(compact)
    if words:
        return len(words) <= _DIRECT_ANSWER_GENERIC_CONCEPT_MAX_WORDS
    return len(compact) <= _DIRECT_ANSWER_GENERIC_KOREAN_CONCEPT_MAX_CHARS


def _contains_concept_keyword(text: str) -> bool:
    for marker in _DIRECT_ANSWER_CONCEPT_KEYWORDS:
        if not marker.isascii():
            if marker in text:
                return True
            continue
        parts = marker.split()
        pattern = r"(?<![A-Za-z0-9])" + r"\s+".join(re.escape(part) for part in parts) + r"(?![A-Za-z0-9])"
        if re.search(pattern, text):
            return True
    return False


def _word_tokens(text: str) -> tuple[str, ...]:
    cleaned = "".join(character if character.isalnum() else " " for character in text)
    return tuple(cleaned.split())


def _contains_direct_answer_blocker(text: str) -> bool:
    return _contains_marker(text, _DIRECT_ANSWER_BLOCKERS)


def _contains_marker(text: str, markers: tuple[str, ...]) -> bool:
    word_text = f" {' '.join(''.join(character if character.isalnum() else ' ' for character in text).split())} "
    for marker in markers:
        if marker.isascii() and marker.replace("-", "").replace(" ", "").isalnum():
            if f" {marker} " in word_text:
                return True
        elif marker in text:
            return True
    return False


def _compact_recommendations(recommendations: object) -> list[dict[str, object]]:
    if not isinstance(recommendations, list):
        return []
    compact: list[dict[str, object]] = []
    for item in recommendations:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "skill": str(item.get("skill", "")),
                "score": _int_value(item.get("score", 0)),
                "confidence": str(item.get("confidence", "low")),
                "matched": _string_list(item.get("matched", [])),
                "next_action": str(item.get("next_action", "")),
                "evidence_boundary": str(item.get("evidence_boundary", "")),
                "wrapper_guidance": str(item.get("wrapper_guidance", "")),
            }
        )
    return compact


def _selected_recommendation(route: dict[str, object]) -> dict[str, object]:
    selected = str(route.get("selected_skill", ""))
    recommendations = route.get("recommendations", [])
    if not isinstance(recommendations, list):
        return {}
    first: dict[str, object] = {}
    for item in recommendations:
        if not isinstance(item, dict):
            continue
        if not first:
            first = item
        if str(item.get("skill", "")) == selected:
            return item
    return first


def _route_next_action(route: dict[str, object], recommendation: dict[str, object]) -> str:
    route_next_action = str(route.get("route_next_action", "")).strip()
    if route_next_action:
        return route_next_action
    action = str(route.get("action", "fallback"))
    if action == "dispatch":
        if str(route.get("selected_skill", "")) == "ultraprocess" and _route_is_coding_status_request(route):
            return "show_coding_handoff_status"
        return str(recommendation.get("next_action") or "dispatch_to_workflow")
    if action == "fallback" and _is_file_lookup_reason(str(route.get("reason", ""))):
        return "answer_file_lookup"
    if action == "fallback" and _is_direct_answer_reason(str(route.get("reason", ""))):
        return "answer_directly"
    if action == "clarify":
        return "answer_clarification"
    return "ask_one_clarification"


def _route_is_coding_status_request(route: dict[str, object]) -> bool:
    reason = str(route.get("reason", "")).lower()
    if "coding progress questions" in reason or "progress/status" in reason:
        return True
    recommendations = route.get("recommendations", [])
    if not isinstance(recommendations, list):
        return False
    for recommendation in recommendations:
        if not isinstance(recommendation, dict):
            continue
        matched = {str(item) for item in recommendation.get("matched", []) if str(item)}
        if {"guard:coding_progress_status", "guard:coding_handoff_status"} & matched:
            return True
    return False


def _route_claim_boundary(route: dict[str, object], recommendation: dict[str, object]) -> str:
    if _is_file_lookup_reason(str(route.get("reason", ""))):
        return "No OMH workflow, execution, or file inspection has started."
    if _is_direct_answer_reason(str(route.get("reason", ""))):
        return "No OMH workflow, picker, handoff, execution, or file inspection has started."
    boundary = str(recommendation.get("evidence_boundary", "")).strip()
    if boundary:
        return boundary
    if str(route.get("action", "")) == "dispatch":
        return "Routing guidance is not workflow execution evidence."
    return "No execution has started."


def _route_explanation_reason(route: dict[str, object]) -> str:
    reason = str(route.get("reason", "")).strip()
    if reason:
        return _human_route_reason(reason)
    clarification = str(route.get("clarification", "")).strip()
    if clarification:
        return clarification
    return "Selected from catalog metadata, trigger phrases, and deterministic guardrail policy."


def _human_route_reason(reason: str) -> str:
    for prefix in (
        "Matched guard/trigger metadata; ",
        "Matched high-level task abstraction before workflow routing. ",
    ):
        if reason.startswith(prefix):
            return _capitalize_sentence(reason[len(prefix) :])
    return reason


def _capitalize_sentence(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    return text[:1].upper() + text[1:]


def _route_explanation_headline(action: str, selected: str, next_action: str) -> str:
    if action == "dispatch":
        return f"Use `{selected}` for this request."
    if action == "clarify":
        return "Ask one question before choosing a workflow."
    if next_action == "answer_file_lookup":
        return "Answer as a file or text lookup."
    if next_action == "answer_directly":
        return "Answer directly in chat."
    return "Keep this in the router until the target is clear."


def _route_explanation_summary(
    action: str,
    selected: str,
    next_action: str,
    next_action_label: str,
    why: str,
) -> str:
    if action == "dispatch":
        return f"`{selected}` is selected because {why} Next action: {next_action_label} (`{next_action}`)."
    if action == "clarify":
        return f"The router needs one clarification before dispatch. Best candidate: `{selected}`."
    if next_action == "answer_file_lookup":
        return f"Answer directly as a file or text lookup; do not dispatch a workflow. Reason: {why}"
    if next_action == "answer_directly":
        return f"Answer directly without opening an OMH workflow. Reason: {why}"
    return f"The router should not dispatch yet. Reason: {why}"


def _route_recommended_reply(
    action: str,
    selected: str,
    next_action: str,
    next_action_label: str,
    not_evidence_yet: list[str],
) -> str:
    if action == "dispatch":
        suffix = not_evidence_reply_suffix(
            not_evidence_yet,
            fallback=" This is routing guidance, not execution evidence.",
        )
        return f"I will use `{selected}` first and start by {next_action_label}.{suffix}"
    if action == "clarify":
        return "I need one clarification before choosing a workflow; no plan or execution has started."
    if next_action == "answer_file_lookup":
        return "I will answer this as a file or text lookup; no file inspection or workflow execution has started."
    if next_action == "answer_directly":
        return "I will answer directly in chat; no OMH workflow, handoff, or execution has started."
    return "I will keep this in the router until the target is clear; no workflow or execution has started."


def _route_primary_action_label(action: str, selected: str, next_action: str) -> str:
    if action == "dispatch":
        return f"Open {selected}"
    if action == "clarify":
        return "Answer clarification"
    if next_action == "answer_file_lookup":
        return "Answer file lookup"
    if next_action == "answer_directly":
        return "Answer directly"
    return "Clarify request"


def _route_primary_action_hint(
    action: str,
    selected: str,
    next_action: str,
    next_action_label: str,
    not_evidence_yet: list[str],
) -> str:
    if action == "dispatch":
        suffix = not_evidence_action_suffix(not_evidence_yet)
        return f"Route to `{selected}` and start by {next_action_label}{suffix}."
    if action == "clarify":
        return "Ask one blocking question, then reroute with the answer."
    if next_action == "answer_directly":
        return "Answer in the current chat without opening a workflow, picker, or handoff."
    return "Answer directly or ask for the missing target before dispatching a workflow."


def _not_evidence_from_boundary(boundary: str) -> list[str]:
    text = boundary.lower()
    if "file inspection" in text:
        items = ["file inspection"]
        if "execution" in text:
            items.append("execution")
        return items
    items: list[str] = []
    for marker, label in _BOUNDARY_MARKER_LABELS:
        if marker in text and label not in items:
            items.append(label)
    peer_review_free_text = text.replace("peer review", "")
    for pattern, label in _BOUNDARY_REGEX_LABELS:
        if pattern.search(peer_review_free_text) and label not in items:
            items.append(label)
    if items:
        return items
    if "prepared" in text:
        return ["execution", "verification", "delivery"]
    if "no execution" in text:
        return ["execution"]
    return ["completion claim without observed evidence"]


def _int_value(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]
