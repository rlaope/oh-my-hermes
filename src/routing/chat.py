from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
import re
import unicodedata
from typing import Any

from ..goal_loop import explicit_loop_invocation_signal
from ..ingress import CHAT_SOURCES, extract_message_text
from .catalog_questions import is_file_or_text_lookup_question, is_skill_catalog_question
from .intent import scrub_diagnostic_status_text
from .policy import (
    CONFIDENCE_LEVELS,
    ROUTE_ACTIONS,
    explicit_skill_invocation as explicit_skill_name,
    is_ambiguous_scores,
    meets_confidence_threshold,
)
from .recommend import recommendation_for_definition, recommend_skills
from .route_plan import build_workflow_route_plan, compact_workflow_route_plan
from .task_cards import classify_task, task_card_recommendation
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
_DIRECT_PICKER_ALIASES = frozenset(("./omh", "/omh", "./skills", "/skills"))
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
    ("performance proof", "performance proof"),
    ("workflow completion", "workflow completion"),
    ("successful workflow completion", "workflow completion"),
    ("runtime, tool, mcp server", "runtime proof"),
    ("tool, mcp server, ci job", "tool invocation"),
    ("mcp server, ci job", "MCP server"),
    ("platform action", "platform action"),
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
    "뭐 있어",
    "무엇이 있어",
    "목록",
    "리스트",
    "할 수 있는",
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
    "what are you working on",
    "where are we",
    "where are we at",
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
    "지금뭐해",
    "지금뭐하는중이야",
    "지금뭐하고있어",
    "작업상황브리핑해줘",
    "작업상황알려줘",
    "진행상황알려줘",
    "현재상태알려줘",
    "현재진행상황",
    "어디까지됐어",
    "어디까지됨",
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
    "pdf",
    "image",
    "poster",
    "summary card",
    "회의",
    "요약",
    "논문",
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

    def to_dict(self) -> dict[str, object]:
        return {
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
    explicit_skill = explicit_skill_invocation(routing_message, definitions)
    task_card = classify_task(message)
    explicit_prefix = _has_explicit_invocation_prefix(routing_message)
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
    elif explicit_loop_signal:
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
    exact_skill = (
        _specific_capability_exact_id_hit(routing_message)
        if catalog_question and not _is_broad_capability_catalog_question(routing_message)
        else None
    )
    if exact_skill is not None:
        definition = _skill_definition_by_name(exact_skill)
        recommendation = recommendation_for_definition(
            definition,
            message,
            matched=("catalog_question", f"name:{exact_skill}"),
            score=12,
            why=f"Matched exact OMH capability `{exact_skill}` from catalog metadata.",
        )
        reason = (
            f"Specific OMH capability question matched `{exact_skill}`; "
            "show that workflow card instead of the generic workflow picker."
        )
        selected_harness = primary_harness_for_skill(exact_skill)
        return _CatalogFastPathResult(
            decision=ChatRouteDecision(
                schema_version=1,
                source=source,
                action="dispatch",
                selected_skill=exact_skill,
                selected_harness=selected_harness,
                candidate_skill=exact_skill,
                candidate_harness=selected_harness,
                confidence="high",
                score=12,
                threshold=min_confidence,
                explicit=False,
                ambiguous=False,
                reason=reason,
                clarification="",
                routing_prompt=_routing_prompt("dispatch", exact_skill, exact_skill, reason, message),
                task_card=None,
                workflow_route_plan=None,
                learning_candidate_card=None,
                recommendations=(recommendation,),
            ),
            catalog_question=catalog_question,
        )
    catalog_picker = (
        not direct_picker
        and catalog_question
        and _generic_omh_catalog_question(routing_message)
    )
    if not direct_picker and not catalog_picker:
        return _CatalogFastPathResult(decision=None, catalog_question=catalog_question)

    matched = ("direct_picker_alias",) if direct_picker else ("catalog_question",)
    score = 12 if direct_picker else 11
    reason = (
        "Direct OMH picker alias; show the workflow picker without scoring every workflow."
        if direct_picker
        else "Catalog question; show the OMH workflow picker instead of asking for shell command approval."
    )
    selected_harness = primary_harness_for_skill(_ROUTER_SKILL)
    recommendation = _router_picker_recommendation(message, matched=matched, score=score)
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
    compact = message.strip().lower().strip(" \t\r\n.!?,;:")
    return compact in _DIRECT_PICKER_ALIASES


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
    if _is_broad_capability_catalog_question(text):
        return True
    if not any(marker in text for marker in ("omh", "oh-my-hermes", "oh my hermes")):
        return False
    named_hits = len(_specific_capability_named_hits(text))
    if named_hits:
        return False
    if any(phrase in text for phrase in _SPECIFIC_CAPABILITY_ALIAS_PHRASES):
        return False
    has_collection = any(marker in text for marker in _GENERIC_CATALOG_COLLECTION_MARKERS)
    has_listing_intent = any(marker in text for marker in _GENERIC_CATALOG_LISTING_MARKERS)
    return has_collection and has_listing_intent


def _router_picker_recommendation(query: str, *, matched: tuple[str, ...], score: int) -> dict[str, object]:
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
        "why": "Matched the OMH workflow picker entry point.",
        "next_action": "choose_skill",
        "evidence_boundary": (
            "Skill picker routing is not plan acceptance, dispatch, execution, review, CI, or verification evidence."
        ),
        "wrapper_guidance": (
            "Render the OMH workflow picker in chat; do not ask the user to approve `omh list` for catalog discovery."
        ),
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
    summary = _route_explanation_summary(action, selected, next_action, why)
    next_action_label = next_action.replace("_", " ") if next_action else ""
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
        "recommended_reply": _route_recommended_reply(action, selected, next_action_label, not_evidence_yet),
        "primary_action_label": _route_primary_action_label(action, selected, next_action_label),
        "primary_action_hint": _route_primary_action_hint(action, selected, next_action_label, not_evidence_yet),
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


def _is_direct_answer_concept_question(text: str, direct_text: str) -> bool:
    if _contains_marker(text, _DIRECT_ANSWER_CONCEPT_HARD_BLOCKERS) or _contains_marker(
        direct_text, _DIRECT_ANSWER_CONCEPT_HARD_BLOCKERS
    ):
        return False
    stripped = direct_text.strip(" \t\r\n.!?¿¡。！？")
    if any(stripped.startswith(marker) for marker in _DIRECT_ANSWER_MULTILINGUAL_CONTEXT_QUESTIONS):
        return False
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
    action = str(route.get("action", "fallback"))
    if action == "dispatch":
        return str(recommendation.get("next_action") or "dispatch_to_workflow")
    if action == "fallback" and _is_file_lookup_reason(str(route.get("reason", ""))):
        return "answer_file_lookup"
    if action == "fallback" and _is_direct_answer_reason(str(route.get("reason", ""))):
        return "answer_directly"
    if action == "clarify":
        return "answer_clarification"
    return "ask_one_clarification"


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


def _route_explanation_summary(action: str, selected: str, next_action: str, why: str) -> str:
    if action == "dispatch":
        return f"`{selected}` is selected because {why} Next action: `{next_action}`."
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
    next_action_label: str,
    not_evidence_yet: list[str],
) -> str:
    if action == "dispatch":
        suffix = not_evidence_reply_suffix(
            not_evidence_yet,
            fallback=" This is routing guidance, not execution evidence.",
        )
        return f"I will use `{selected}` first and start with {next_action_label}.{suffix}"
    if action == "clarify":
        return "I need one clarification before choosing a workflow; no plan or execution has started."
    if next_action_label == "answer file lookup":
        return "I will answer this as a file or text lookup; no file inspection or workflow execution has started."
    if next_action_label == "answer directly":
        return "I will answer directly in chat; no OMH workflow, handoff, or execution has started."
    return "I will keep this in the router until the target is clear; no workflow or execution has started."


def _route_primary_action_label(action: str, selected: str, next_action_label: str) -> str:
    if action == "dispatch":
        return f"Open {selected}"
    if action == "clarify":
        return "Answer clarification"
    if next_action_label == "answer file lookup":
        return "Answer file lookup"
    if next_action_label == "answer directly":
        return "Answer directly"
    return "Clarify request"


def _route_primary_action_hint(
    action: str,
    selected: str,
    next_action_label: str,
    not_evidence_yet: list[str],
) -> str:
    if action == "dispatch":
        suffix = not_evidence_action_suffix(not_evidence_yet)
        return f"Route to `{selected}` and run `{next_action_label}`{suffix}."
    if action == "clarify":
        return "Ask one blocking question, then reroute with the answer."
    if next_action_label == "answer directly":
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
