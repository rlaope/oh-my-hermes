from __future__ import annotations

import hashlib
from functools import lru_cache
import re
from typing import Any, Iterable

from ..routing.missed_route import is_missed_omh_workflow_feedback


LEARNING_CANDIDATE_CARD_SCHEMA_VERSION = "learning_candidate_card/v1"
LEARNING_CANDIDATE_SCOPE_SCHEMA_VERSION = "learning_candidate_scope/v1"
LEARNING_CANDIDATE_TARGETS = ("skill_candidate", "memory_candidate", "session_only", "review_first")
LEARNING_CANDIDATE_STATUS = "prepared_not_observed"

_EXPLICIT_LEARN_SIGNALS = (
    "/learn",
    "learn this",
    "remember this pattern",
    "remember this",
    "make a skill from this",
    "create a skill from this",
    "turn this into a skill",
    "save this as a skill",
    "use this next time",
    "next time",
    "from now on",
    "다음부터 이렇게",
    "다음부터",
    "앞으로는",
    "이걸 학습해",
    "이거 학습해",
    "학습해",
    "이 패턴 기억해",
    "기억해",
    "방금 한 방식 skill로 남겨",
    "방금 한 방식 스킬로 남겨",
    "skill로 남겨",
    "스킬로 남겨",
)
_SKILL_FORCING_SIGNALS = (
    "make a skill from this",
    "create a skill from this",
    "turn this into a skill",
    "save this as a skill",
    "remember this pattern",
    "이 패턴 기억해",
    "방금 한 방식 skill로 남겨",
    "방금 한 방식 스킬로 남겨",
    "skill로 남겨",
    "스킬로 남겨",
)
_BRIDGE_FORCING_SIGNALS = _SKILL_FORCING_SIGNALS + (
    "/learn",
    "learn this",
    "이걸 학습해",
    "이거 학습해",
)
_PROCEDURE_TOKENS = (
    "workflow",
    "runbook",
    "procedure",
    "checklist",
    "steps",
    "step",
    "pattern",
    "command",
    "commands",
    "tooling",
    "tool",
    "script",
    "verify",
    "verification",
    "test",
    "tests",
    "lint",
    "when ",
    "whenever",
    "after ",
    "before ",
    "if ",
    "then ",
    "run ",
    "use ",
    "do ",
    "워크플로",
    "워크플로우",
    "런북",
    "절차",
    "방식",
    "패턴",
    "단계",
    "명령",
    "커맨드",
    "검증",
    "테스트",
    "도구",
    "실행",
    "때 ",
    "하면",
    "먼저",
)
_COMMAND_TOKENS = (
    "git ",
    "gh ",
    "uv ",
    "python ",
    "pytest",
    "ruff",
    "mypy",
    "npm ",
    "pnpm ",
    "yarn ",
    "make ",
    "omh ",
    "omx ",
    "hermes ",
)
_PREFERENCE_TOKENS = (
    "i prefer",
    "my preference",
    "prefer ",
    "always ",
    "never ",
    "default to",
    "use korean",
    "in korean",
    "concise",
    "brief",
    "tone",
    "format",
    "style",
    "선호",
    "좋아",
    "싫어",
    "항상",
    "절대",
    "한국어",
    "짧게",
    "간결",
    "말투",
    "형식",
    "포맷",
)
_CROSS_CHANNEL_TOKENS = (
    "cross-channel",
    "cross channel",
    "other channel",
    "different channel",
    "channel ",
    "thread ",
    "slack channel",
    "discord channel",
    "dm ",
    "다른 채널",
    "채널",
    "스레드",
)
_CONFLICT_TOKENS = (
    "conflict",
    "conflicting",
    "contradict",
    "contradicts",
    "ambiguous",
    "not sure",
    "maybe",
    "might",
    "충돌",
    "모순",
    "애매",
    "확실하지",
)
_TRANSIENT_STATE_TOKENS = (
    "blocked on ci",
    "ci is failing",
    "current pr",
    "this pr",
    "this branch",
    "current branch",
    "this run",
    "current run",
    "this task",
    "current task",
    "이번 pr",
    "현재 pr",
    "이번 작업",
    "현재 작업",
    "이번 런",
)

_TRANSIENT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "channel_or_thread_ref",
        re.compile(
            r"(?i)\b(?:slack|discord)?\s*(?:channel|thread|dm)\s+[#@]?[A-Za-z0-9_.:-]{2,120}\b|#[A-Za-z][A-Za-z0-9_-]{1,80}\b"
        ),
    ),
    ("pull_request_number", re.compile(r"(?i)\b(?:pr|pull request)\s*#?\d+\b")),
    ("commit_sha", re.compile(r"(?i)\b(?:commit|sha)\s+[0-9a-f]{7,40}\b|\b[0-9a-f]{12,40}\b")),
    (
        "run_id",
        re.compile(r"(?i)\b\d{8}t\d{6,}z[-A-Za-z0-9_.:]*\b|\brun[_:-][A-Za-z0-9_.:-]{6,}\b"),
    ),
    ("process_id", re.compile(r"(?i)\b(?:pid|process id)\s*[:#]?\s*\d+\b|\bproc_[A-Za-z0-9_:-]{6,}\b")),
    ("branch_ref", re.compile(r"(?i)\bbranch\s+[A-Za-z0-9._/-]{3,120}\b")),
    ("task_state_ref", re.compile(r"(?i)\b(?:task|job)\s*#?[A-Za-z0-9_.:-]{4,120}\b")),
)


def build_learning_candidate_card(
    message: str,
    *,
    source: str = "generic",
    source_metadata: dict[str, str] | None = None,
    selected_workflow: str = "",
    selected_harness: str = "",
    thread_key: str = "",
    executor_runtime: str = "",
) -> dict[str, object] | None:
    if selected_workflow == "workflow-learning" and is_missed_omh_workflow_feedback(message):
        return None

    signal = detect_learning_signal(message)
    if signal is None:
        return None

    sanitized, redactions = sanitize_learning_text(message)
    persistence_target = classify_learning_persistence_target(message, sanitized=sanitized, signal=signal, redactions=redactions)
    recommended_workflow = _recommended_workflow(persistence_target)
    summary = _candidate_summary(persistence_target, sanitized)
    card = {
        "schema_version": LEARNING_CANDIDATE_CARD_SCHEMA_VERSION,
        "card_id": _card_id(source, sanitized, persistence_target),
        "status": LEARNING_CANDIDATE_STATUS,
        "learning_signal": signal,
        "persistence_target": persistence_target,
        "recommended_workflow": recommended_workflow,
        "primary_action": _primary_action(persistence_target),
        "summary": summary,
        "scope": build_learning_candidate_scope(
            source=source,
            source_metadata=source_metadata or {},
            selected_workflow=selected_workflow or recommended_workflow,
            selected_harness=selected_harness,
            thread_key=thread_key,
            executor_runtime=executor_runtime,
        ),
        "sanitization": {
            "transient_identifier_categories": redactions,
            "prompt_uses_sanitized_observed_facts": True,
            "excluded_from_prompt_and_summary": [
                "pull request numbers",
                "commit SHAs",
                "run IDs",
                "process IDs",
                "one-off channel/thread/task state",
            ],
        },
        "review": {
            "required": persistence_target in {"memory_candidate", "review_first"},
            "review_workflow": "memory-sync" if persistence_target in {"memory_candidate", "review_first"} else "",
            "human_gate": "review_before_persistence",
        },
        "claim_boundary": (
            "This card and any /learn prompt are prepared_not_observed; they are not skill creation evidence, "
            "memory mutation evidence, workflow execution evidence, review evidence, CI evidence, or merge evidence."
        ),
        "not_observed": [
            "Hermes /learn execution",
            "skill creation",
            "memory write",
            "future behavior change",
            "review approval",
        ],
        "available_actions": _available_actions(persistence_target),
    }
    if persistence_target == "skill_candidate":
        card["learn_prompt"] = build_copy_ready_learn_prompt(sanitized)
    return card


def build_learning_candidate_scope(
    *,
    source: str,
    source_metadata: dict[str, str],
    selected_workflow: str,
    selected_harness: str = "",
    thread_key: str = "",
    executor_runtime: str = "",
) -> dict[str, object]:
    return {
        "schema_version": LEARNING_CANDIDATE_SCOPE_SCHEMA_VERSION,
        "source": source,
        "project_ref": source_metadata.get("project_ref", ""),
        "channel_ref": source_metadata.get("channel_ref", ""),
        "thread_ref": source_metadata.get("thread_ref", "") or thread_key,
        "target_ref": source_metadata.get("target_ref", ""),
        "workflow": source_metadata.get("workflow_ref", "") or selected_workflow,
        "harness": selected_harness,
        "executor_runtime": executor_runtime
        or source_metadata.get("executor_ref", "")
        or source_metadata.get("runtime_ref", ""),
    }


def detect_learning_signal(message: str) -> dict[str, object] | None:
    return _copy_learning_signal(_detect_learning_signal_cached(message))


@lru_cache(maxsize=4096)
def _detect_learning_signal_cached(message: str) -> dict[str, object] | None:
    normalized = _fold(message)
    workflow_learning_context = "workflow learning" in normalized or "learn from this workflow" in normalized
    if workflow_learning_context and not any(phrase in normalized for phrase in _folded_bridge_forcing_signals()):
        return None
    for phrase, folded_phrase in _folded_explicit_learn_signals():
        if folded_phrase in normalized:
            signal_type = "skill_request" if phrase in _SKILL_FORCING_SIGNALS else "explicit_learn_request"
            if phrase in {"next time", "from now on", "다음부터", "다음부터 이렇게", "앞으로는"}:
                signal_type = "user_correction"
            if phrase == "/learn":
                signal_type = "hermes_learn_bridge"
            return {
                "type": signal_type,
                "matched": phrase,
                "source": "user_message",
            }
    return None


def _copy_learning_signal(signal: dict[str, object] | None) -> dict[str, object] | None:
    return dict(signal) if signal else None


@lru_cache(maxsize=1)
def _folded_bridge_forcing_signals() -> tuple[str, ...]:
    return tuple(_fold(phrase) for phrase in _BRIDGE_FORCING_SIGNALS)


@lru_cache(maxsize=1)
def _folded_explicit_learn_signals() -> tuple[tuple[str, str], ...]:
    return tuple((phrase, _fold(phrase)) for phrase in _EXPLICIT_LEARN_SIGNALS)


def classify_learning_persistence_target(
    message: str,
    *,
    sanitized: str | None = None,
    signal: dict[str, object] | None = None,
    redactions: list[str] | None = None,
) -> str:
    text = sanitized if sanitized is not None else sanitize_learning_text(message)[0]
    folded = _fold(message)
    sanitized_folded = _fold(text)
    signal = signal or detect_learning_signal(message) or {}
    redactions = redactions if redactions is not None else sanitize_learning_text(message)[1]

    if _contains_any(folded, _CROSS_CHANNEL_TOKENS) or _contains_any(folded, _CONFLICT_TOKENS):
        return "review_first"

    has_procedure = _contains_any(sanitized_folded, _PROCEDURE_TOKENS) or _contains_any(sanitized_folded, _COMMAND_TOKENS)
    has_preference = _contains_any(sanitized_folded, _PREFERENCE_TOKENS)
    has_transient = bool(redactions) or _contains_any(folded, _TRANSIENT_STATE_TOKENS)

    if has_transient and not has_procedure:
        return "session_only"
    if str(signal.get("matched", "")) in _SKILL_FORCING_SIGNALS:
        return "skill_candidate"
    if has_procedure:
        return "skill_candidate"
    if has_preference:
        return "memory_candidate"
    if has_transient:
        return "session_only"
    return "review_first"


def sanitize_learning_text(message: str) -> tuple[str, list[str]]:
    text = _strip_learning_signal(message)
    redactions: list[str] = []
    for category, pattern in _TRANSIENT_PATTERNS:
        if pattern.search(text):
            redactions.append(category)
            text = pattern.sub(_replacement_for_category(category), text)
    text = _normalize_space(text)
    text = _trim_trailing_one_off_state(text)
    return text[:900].strip(), _unique(redactions)


def build_copy_ready_learn_prompt(sanitized_observed_facts: str) -> dict[str, object]:
    observed = sanitized_observed_facts.strip() or "The user explicitly requested a reusable learning artifact, but the durable procedure details need review."
    copy_text = "\n".join(
        [
            "/learn",
            "Use observed facts only. Create a reusable Hermes skill from the procedure below.",
            "",
            "Observed reusable procedure:",
            observed,
            "",
            "The skill must include:",
            "- Trigger conditions for when Hermes should use it.",
            "- Exact steps in order, using only reusable facts from the observed procedure.",
            "- Pitfalls and false positives to avoid.",
            "- Verification commands or checks when applicable.",
            "- When not to use the skill.",
            "",
            "Exclude transient IDs and one-off state: PR numbers, commit SHAs, run IDs, process IDs, channel/thread/task state, branch-specific status, and temporary review or CI state.",
            "Preserve the evidence boundary: this copied prompt is prepared_not_observed and is not proof that a Hermes skill was created.",
        ]
    )
    return {
        "schema_version": "hermes_learn_prompt/v1",
        "status": LEARNING_CANDIDATE_STATUS,
        "command": "/learn",
        "copy_text": copy_text,
        "claim_boundary": "Copy-ready prompt only; Hermes Agent /learn owns any skill creation evidence.",
    }


def validate_learning_candidate_card(card: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if card.get("schema_version") != LEARNING_CANDIDATE_CARD_SCHEMA_VERSION:
        errors.append("schema_version must be learning_candidate_card/v1")
    if card.get("status") != LEARNING_CANDIDATE_STATUS:
        errors.append("status must be prepared_not_observed")
    if card.get("persistence_target") not in LEARNING_CANDIDATE_TARGETS:
        errors.append("persistence_target is unsupported")
    scope = card.get("scope")
    if not isinstance(scope, dict) or scope.get("schema_version") != LEARNING_CANDIDATE_SCOPE_SCHEMA_VERSION:
        errors.append("scope must be learning_candidate_scope/v1")
    if card.get("persistence_target") == "skill_candidate":
        prompt = card.get("learn_prompt")
        if not isinstance(prompt, dict) or prompt.get("command") != "/learn":
            errors.append("skill_candidate must include a /learn prompt")
    if "prepared_not_observed" not in str(card.get("claim_boundary", "")):
        errors.append("claim_boundary must preserve prepared_not_observed")
    return errors


def _recommended_workflow(target: str) -> str:
    if target in {"memory_candidate", "review_first"}:
        return "memory-sync"
    if target == "session_only":
        return "oh-my-hermes"
    return "workflow-learning"


def _primary_action(target: str) -> str:
    if target == "skill_candidate":
        return "copy_learn_prompt"
    if target in {"memory_candidate", "review_first"}:
        return "prepare_memory_sync"
    return "show_learning_candidate"


def _available_actions(target: str) -> list[str]:
    actions = ["show_learning_candidate", "show_status"]
    if target == "skill_candidate":
        actions.insert(0, "copy_learn_prompt")
    if target in {"memory_candidate", "review_first"}:
        actions.insert(0, "prepare_memory_sync")
        actions.append("show_memory_status")
    return actions


def _candidate_summary(target: str, sanitized: str) -> str:
    fact = sanitized.strip()
    if target == "skill_candidate":
        return _truncate(f"Reusable skill candidate from observed procedure: {fact}", 360)
    if target == "memory_candidate":
        return _truncate(f"Durable user preference candidate for memory review: {fact}", 360)
    if target == "session_only":
        return "Session-only learning signal; do not persist transient task, PR, run, process, branch, or channel state."
    return "Review-first learning signal; cross-channel, conflicting, or underspecified context needs memory curation review before persistence."


def _strip_learning_signal(message: str) -> str:
    text = message.strip()
    for phrase in sorted(_EXPLICIT_LEARN_SIGNALS, key=len, reverse=True):
        pattern = re.compile(r"\s+".join(re.escape(part) for part in phrase.split()), re.IGNORECASE)
        match = pattern.search(text)
        if match is None:
            continue
        stripped = (text[: match.start()] + text[match.end() :]).strip(" :-\n\t")
        return stripped or text
    return text


def _replacement_for_category(category: str) -> str:
    return {
        "channel_or_thread_ref": "channel/thread context",
        "pull_request_number": "pull request",
        "commit_sha": "commit",
        "run_id": "run",
        "process_id": "process",
        "branch_ref": "branch",
        "task_state_ref": "task",
    }.get(category, "transient state")


def _trim_trailing_one_off_state(text: str) -> str:
    return re.sub(r"(?i)\b(?:for now|right now|only for this task|only for this run|이번만|이번 작업만)\b", "", text).strip(" .:-")


def _contains_any(text: str, needles: Iterable[str]) -> bool:
    return any(needle and needle in text for needle in needles)


@lru_cache(maxsize=8192)
def _fold(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _normalize_space(text: str) -> str:
    return " ".join(text.replace("\n", " ").split())


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _card_id(source: str, sanitized: str, target: str) -> str:
    seed = "|".join((source.strip().lower(), sanitized.strip().lower(), target))
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"learning-candidate-{digest}"
