from __future__ import annotations

from functools import lru_cache
import re

from .localization import normalized_phrase, routing_tokens
from .intent import META_OR_FEEDBACK_INTENTS, classify_workflow_intent
from .policy import _doctor_health_guard_applies


TASK_CARD_SCHEMA_VERSION = "omh_task_card/v1"
TASK_CARD_ROUTE_LEVEL = "task_abstraction"
TASK_CARD_MAINTENANCE_ROUTE_LEVEL = "operator_maintenance_command"

_RUNTIME_PORTABILITY_PHRASES = (
    "another macbook",
    "another mac",
    "new macbook",
    "new machine",
    "other machine",
    "same setup",
    "reproduce this setup",
    "reproduce the setup",
    "restore this setup",
    "environment reproduction",
    "runtime portability",
    "move the gateway",
    "transfer the gateway",
    "private github",
    "backup the state",
    "backup to github",
    "migrate this setup",
    "다른 맥북",
    "새 맥북",
    "다른 컴퓨터",
    "같은 세팅",
    "세팅 재현",
    "환경 재현",
    "런타임 재현",
    "백업",
    "복원",
    "옮기",
    "마이그레이션",
    "게이트웨이 이전",
    "프라이빗 깃허브",
    "개인 깃허브",
)
_RUNTIME_CONTEXT_TOKENS = frozenset(
    {
        "hermes",
        "friren",
        "omh",
        "agent",
        "gateway",
        "discord",
        "slack",
        "telegram",
        "bot",
        "responder",
        "runtime",
        "plugin",
        "헤르메스",
        "프리렌",
        "에이전트",
        "게이트웨이",
        "디스코드",
        "슬랙",
        "텔레그램",
        "봇",
        "런타임",
        "플러그인",
    }
)
_RUNTIME_CONTEXT_NORMALIZED_TOKENS = frozenset(normalized_phrase(term) for term in _RUNTIME_CONTEXT_TOKENS)
_ROUTER_DESIGN_CONTEXT_PHRASES = (
    "higher-level task abstraction",
    "higher level task abstraction",
    "task abstraction",
    "not a migration workflow",
    "not migration workflow",
    "router design",
    "routing design",
    "route this wrong",
    "wrong route",
    "wrong workflow",
    "learn from this run",
    "상위레벨",
    "상위 레벨",
    "작업 추상화",
    "태스크 추상화",
    "마이그레이션이라는 개념",
    "마이그레이션 워크플로",
    "라우팅 설계",
    "잘못 라우팅",
    "워크플로 학습",
    "워크플로우 학습",
    "라우팅 피드백",
    "라우터 강화",
    "라우터강화",
    "라우터 개선",
    "라우터개선",
    "플랜으로 잡",
    "omh가 얼마나 관여",
    "omh를 얼마나 관여",
    "omh 관여",
    "omh관여",
    "omh 관여도",
    "omh관여도",
)
_MAINTENANCE_COMMAND_ALIASES = {
    "update": ("update", "upgrade", "refresh", "업데이트", "업뎃", "갱신"),
    "setup": ("setup", "set up", "셋업", "설정"),
    "doctor": ("doctor", "health", "diagnose", "닥터", "진단", "헬스"),
    "uninstall": ("uninstall", "remove", "purge", "삭제", "제거", "언인스톨"),
    "install": ("install", "설치"),
    "list": ("list", "목록", "리스트"),
}
_MAINTENANCE_SURFACE_PHRASES = ("omh", "./omh", "/omh", "oh my hermes", "oh-my-hermes")
_MAINTENANCE_RUN_CUES = (
    "run",
    "please",
    "돌려",
    "돌려줘",
    "실행",
    "실행해",
    "해줘",
    "해주세요",
    "해",
)
_MAINTENANCE_EXPLANATION_CUES = (
    "guide",
    "docs",
    "documentation",
    "explain",
    "what is",
    "how do",
    "why",
    "문서",
    "가이드",
    "설명",
    "뭐야",
    "무엇",
    "어떻게",
    "왜",
)
_MAINTENANCE_HEALTH_QUESTION_CUES = (
    "did update work",
    "update worked",
    "update ok",
    "version unchanged",
    "same version",
    "was update applied",
    "잘 된",
    "잘된",
    "잘 됐",
    "잘됐",
    "됐는지",
    "되었는지",
    "제대로",
    "반영",
    "버전",
    "확인",
)
_MAINTENANCE_CODE_CHANGE_CUES = (
    "implement",
    "implementation",
    "code change",
    "edit",
    "patch",
    "fix",
    "pr",
    "branch",
    "test",
    "tests",
    "router",
    "routing",
    "workflow implementation",
    "구현",
    "수정",
    "패치",
    "테스트",
    "브랜치",
    "라우터",
    "라우팅",
)
_MAINTENANCE_FILLER_TOKENS = frozenset(
    {
        "can",
        "you",
        "please",
        "run",
        "the",
        "command",
        "cli",
        "omh",
        "oh",
        "my",
        "hermes",
        "좀",
        "제발",
        "명령",
        "명령어",
        "실행",
    }
)
_CODE_CLEANUP_ACTION_TOKENS = frozenset(
    normalized_phrase(term)
    for term in (
        "cleanup",
        "clean",
        "remove",
        "dedupe",
        "deduplicate",
        "simplify",
        "refactor",
        "refactoring",
        "lock",
        "정리",
        "제거",
        "중복",
        "리팩터링",
    )
)
_CODE_CLEANUP_TARGET_TOKENS = frozenset(
    normalized_phrase(term)
    for term in (
        "code",
        "branch",
        "branches",
        "router",
        "routing",
        "test",
        "tests",
        "regression",
        "behavior",
        "implementation",
        "코드",
        "라우터",
        "라우팅",
        "테스트",
        "회귀",
        "구현",
    )
)
_EXECUTOR_STATUS_CONTEXT_PHRASES = (
    "codex",
    "claude code",
    "coding agent",
    "coding handoff",
    "coding work",
    "executor",
    "코덱스",
    "클로드",
    "코딩 에이전트",
    "코딩 작업",
    "코딩 핸드오프",
)
_EXECUTOR_STATUS_SIGNAL_PHRASES = (
    "latest status",
    "current status",
    "status of",
    "handoff status",
    "coding handoff",
    "tests passed",
    "pr is open",
    "pr opened",
    "what is still missing",
    "what's still missing",
    "what evidence is still missing",
    "progress",
    "running",
    "session",
    "진행상태",
    "진행 상황",
)
_EXECUTOR_STATUS_META_EXCLUSION_PHRASES = (
    "developer test",
    "developer note",
    "setup test",
    "token only",
    "not asking to implement",
    "vocabulary",
    "route:",
    "routing",
    "router",
    "용어",
    "라우팅",
    "라우터",
    "라우터 강화",
)


def classify_task(message: str) -> dict[str, object] | None:
    """Classify high-level user tasks before choosing lower-level workflow rails."""
    normalized = normalized_phrase(message)
    compact = normalized.replace(" ", "")
    tokens = set(routing_tokens(message, stopwords=set()))
    tokens.update(normalized.split())
    intent = classify_workflow_intent(message)

    maintenance_command = _maintenance_command(normalized, compact, tokens)
    if maintenance_command:
        return _maintenance_command_card(maintenance_command)
    if _is_router_design_feedback(normalized, compact, tokens, intent):
        return _router_design_feedback_card()
    if _is_runtime_portability(normalized, compact, tokens):
        return _runtime_portability_card()
    return None


def task_card_recommendation(card: dict[str, object]) -> dict[str, object]:
    task_type = str(card.get("task_type", "unknown_task"))
    selected = str(card.get("selected_workflow_rail", "oh-my-hermes"))
    return {
        "skill": selected,
        "score": int(card.get("score", 12)),
        "confidence": str(card.get("confidence", "high")),
        "matched": [f"task_card:{task_type}", str(card.get("route_level", TASK_CARD_ROUTE_LEVEL))],
        "next_action": str(card.get("recommended_next_action", "show_workflow_guidance")),
        "evidence_boundary": str(card.get("claim_boundary", "")),
        "wrapper_guidance": str(card.get("wrapper_guidance", "")),
        "why": str(card.get("routing_reason", "Matched high-level task abstraction before workflow routing.")),
    }


def _maintenance_command(normalized: str, compact: str, tokens: set[str]) -> str | None:
    if not _maintenance_surface_hit(normalized, compact, tokens):
        return None
    if _doctor_health_guard_applies(normalized, routing_tokens(normalized)):
        return None
    for command, aliases in _MAINTENANCE_COMMAND_ALIASES.items():
        if (
            _maintenance_alias_hit(command, aliases, normalized, compact, tokens)
            and _is_near_exact_maintenance_request(
                normalized,
                compact,
                tokens,
            )
        ):
            return command
    return None


def _maintenance_surface_hit(normalized: str, compact: str, tokens: set[str]) -> bool:
    if "omh" in tokens or "oh-my-hermes" in normalized or "oh my hermes" in normalized:
        return True
    return any(surface_compact in compact for _surface, _surface_normalized, surface_compact in _maintenance_surfaces())


def _maintenance_alias_hit(
    command: str,
    aliases: tuple[str, ...],
    normalized: str,
    compact: str,
    tokens: set[str],
) -> bool:
    for _alias, normalized_alias, compact_alias in _normalized_phrase_options(aliases):
        for _surface, normalized_surface, compact_surface in _maintenance_surfaces():
            if f"{normalized_surface} {normalized_alias}" in normalized:
                return True
            if f"{compact_surface}{compact_alias}" in compact:
                return True
        if normalized.startswith("omh") and (normalized_alias in normalized or compact_alias in compact):
            return True
    return command in tokens and "omh" in tokens


def _is_near_exact_maintenance_request(normalized: str, compact: str, tokens: set[str]) -> bool:
    if _phrase_hit(_MAINTENANCE_CODE_CHANGE_CUES, normalized, compact):
        return False
    if _is_update_health_question(normalized, compact):
        return False
    explain_hit = _phrase_hit(_MAINTENANCE_EXPLANATION_CUES, normalized, compact)
    run_hit = _phrase_hit(_MAINTENANCE_RUN_CUES, normalized, compact)
    exact_hit = compact in _maintenance_exact_compact_requests()
    meaningful = {token for token in tokens if token not in _MAINTENANCE_FILLER_TOKENS}
    if exact_hit:
        return True
    if explain_hit:
        return False
    if run_hit and len(meaningful) <= 8:
        return True
    return normalized.lstrip("`'\"“”‘’ ").startswith(("omh", "./omh", "/omh")) and len(meaningful) <= 4


def _is_update_health_question(normalized: str, compact: str) -> bool:
    return _phrase_hit(("update", "업데이트", "업뎃", "갱신"), normalized, compact) and _phrase_hit(
        _MAINTENANCE_HEALTH_QUESTION_CUES,
        normalized,
        compact,
    )


def _is_runtime_portability(normalized: str, compact: str, tokens: set[str]) -> bool:
    phrase_hit = _phrase_hit(_RUNTIME_PORTABILITY_PHRASES, normalized, compact)
    if not phrase_hit:
        return False
    context_hits = len(tokens & _RUNTIME_CONTEXT_NORMALIZED_TOKENS)
    if context_hits:
        return True
    return _phrase_hit(("gateway", "bot", "responder", "게이트웨이", "봇", "응답자"), normalized, compact)


def _without_diagnostic_status_lines(normalized: str) -> str:
    markers = (
        "[omh awareness]",
        "[omh route hint]",
        "[omh]",
        "native bridge status context",
        "evidence boundary",
        "latest runtime run",
        "selected_workflow=",
        "mentioned_workflows=",
        "mentioned_runtime_terms=",
        "not_executed=",
        "intent_class=",
        "status=",
        "workflow=",
        "hints=",
    )
    kept: list[str] = []
    for line in normalized.splitlines() or [normalized]:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("[omh"):
            stripped = re.sub(r"^\[omh(?:\s+awareness|\s+route\s+hint)?\]\s*", "", stripped).strip()
            if not stripped:
                continue
        stripped = re.sub(r"\bnative bridge status context\.?", "", stripped).strip()
        stripped = re.sub(r"\bevidence boundary:[^.]*\.?", "", stripped).strip()
        stripped = re.sub(r"\blatest runtime run:[^.]*\.?", "", stripped).strip()
        if not stripped:
            continue
        if stripped.startswith(("native bridge status context", "evidence boundary", "latest runtime run")):
            continue
        if any(marker in stripped for marker in markers):
            fragments = [fragment.strip() for fragment in re.split(r"[;|]", stripped)]
            user_fragments = [fragment for fragment in fragments if fragment and not any(marker in fragment for marker in markers)]
            if user_fragments:
                kept.append(" ".join(user_fragments))
            continue
        kept.append(stripped)
    return "\n".join(kept)


def _diagnostic_region_router_feedback(normalized: str, compact: str) -> bool:
    subject = _phrase_hit(("omh", "omh가", "omh를", "omh의", "oh-my-hermes", "oh my hermes", "router", "routing", "route hint", "라우터", "라우팅"), normalized, compact)
    evaluation = _phrase_hit(("usage evaluation", "usability evaluation", "usage analysis", "router improvement", "router hardening", "route improvement", "evaluate omh", "why omh", "사용성 평가", "사용성평가", "안쓴이유", "안 쓴 이유", "덜 쓴 이유", "덜쓴 이유", "덜 썼", "덜썼", "부족했던 점", "부족한 점", "라우터 강화", "라우터강화", "라우터 개선", "플랜으로 잡", "반복해서 강화"), normalized, compact)
    return subject and evaluation


def _is_router_design_feedback(normalized: str, compact: str, tokens: set[str], intent: object) -> bool:
    structural_cues = set(getattr(intent, "structural_cues", ()))
    diagnostic_status_context = "diagnostic_status_context" in structural_cues
    evaluation_region = _without_diagnostic_status_lines(normalized) if diagnostic_status_context else normalized
    evaluation_compact = evaluation_region.replace(" ", "")
    if _is_code_cleanup_request(evaluation_region, tokens):
        return False
    if _is_executor_status_question(evaluation_region, evaluation_compact, tokens):
        return False
    phrase_hit = _phrase_hit(_ROUTER_DESIGN_CONTEXT_PHRASES, evaluation_region, evaluation_compact)
    if phrase_hit:
        return True
    if "missed route" in evaluation_region or "workflow-learning" in evaluation_region:
        return False
    if diagnostic_status_context:
        return _diagnostic_region_router_feedback(evaluation_region, evaluation_compact)
    if (
        getattr(intent, "intent_class", "") in META_OR_FEEDBACK_INTENTS
        and not bool(getattr(intent, "explicit_execution", False))
        and (
            (not diagnostic_status_context and bool(getattr(intent, "mentioned_workflows", ())))
            or (not diagnostic_status_context and bool(getattr(intent, "mentioned_runtime_terms", ())))
            or bool(getattr(intent, "missing_requirements_cues", ()))
            or _phrase_hit(
                (
                    "route",
                    "routing",
                    "router",
                    "workflow",
                    "workflow route",
                    "coding handoff",
                    "coding delegate",
                    "codex",
                    "라우팅",
                    "라우터",
                    "워크플로",
                    "워크플로우",
                    "코딩 핸드오프",
                ),
                evaluation_region,
                evaluation_compact,
            )
        )
    ):
        return True
    if (
        _phrase_hit(("피드백",), normalized, compact)
        and "omh" in normalized
        and _phrase_hit(("라우팅", "라우터", "워크플로", "워크플로우", "설계", "추상화"), normalized, compact)
    ):
        return True
    return False


def _is_executor_status_question(evaluation_region: str, evaluation_compact: str, tokens: set[str]) -> bool:
    if _phrase_hit(_EXECUTOR_STATUS_META_EXCLUSION_PHRASES, evaluation_region, evaluation_compact):
        return False
    executor_context = _phrase_hit(_EXECUTOR_STATUS_CONTEXT_PHRASES, evaluation_region, evaluation_compact)
    status_signal = _phrase_hit(_EXECUTOR_STATUS_SIGNAL_PHRASES, evaluation_region, evaluation_compact) or bool(
        {"status", "progress", "running", "session", "handoff"} & tokens
    )
    return executor_context and status_signal


def _is_code_cleanup_request(evaluation_region: str, tokens: set[str]) -> bool:
    action = bool(_CODE_CLEANUP_ACTION_TOKENS & tokens) or _phrase_hit(
        (
            "remove duplicated",
            "remove duplicate",
            "lock behavior",
            "regression tests",
            "before refactoring",
            "cleanup code",
            "clean up code",
        ),
        evaluation_region,
        evaluation_region.replace(" ", ""),
    )
    target = bool(_CODE_CLEANUP_TARGET_TOKENS & tokens)
    return action and target


def _phrase_hit(phrases: tuple[str, ...], normalized: str, compact: str) -> bool:
    for _phrase, normalized_phrase_value, compact_phrase_value in _normalized_phrase_options(phrases):
        if normalized_phrase_value in normalized or compact_phrase_value in compact:
            return True
    return False


@lru_cache(maxsize=128)
def _normalized_phrase_options(phrases: tuple[str, ...]) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (phrase, normalized, normalized.replace(" ", ""))
        for phrase in phrases
        if (normalized := normalized_phrase(phrase))
    )


@lru_cache(maxsize=1)
def _maintenance_surfaces() -> tuple[tuple[str, str, str], ...]:
    return _normalized_phrase_options(_MAINTENANCE_SURFACE_PHRASES)


@lru_cache(maxsize=1)
def _maintenance_exact_compact_requests() -> frozenset[str]:
    return frozenset(
        f"{surface_compact}{alias_compact}"
        for _surface, _normalized_surface, surface_compact in _maintenance_surfaces()
        for aliases in _MAINTENANCE_COMMAND_ALIASES.values()
        for _alias, _normalized_alias, alias_compact in _normalized_phrase_options(aliases)
    )


def _runtime_portability_card() -> dict[str, object]:
    return {
        "schema_version": TASK_CARD_SCHEMA_VERSION,
        "task_type": "runtime_portability",
        "route_level": TASK_CARD_ROUTE_LEVEL,
        "confidence": "high",
        "score": 60,
        "selected_workflow_rail": "agent-ops-review",
        "recommended_next_action": "prepare_agent_ops_review",
        "user_facing_summary": (
            "This is a runtime portability task with one responder invariant, not a migration workflow."
        ),
        "not_a_workflow": ["migration", "backup", "private_repo_upload", "gateway_transfer"],
        "operation_primitives": [
            "inventory",
            "package",
            "credential_policy",
            "distribution",
            "restore",
            "verify",
            "gateway_ownership_transfer",
            "liveness_monitoring",
        ],
        "workflow_rails": [
            {
                "skill": "agent-ops-review",
                "purpose": "Own the top-level operating card, blockers, risks, and next safe action.",
            },
            {
                "skill": "toolbelt-readiness",
                "purpose": "Check local CLIs, Hermes paths, plugin state, credentials, and missing tools.",
            },
            {
                "skill": "gateway-intent-card",
                "purpose": "Model origin, thread, delivery, responder ownership, and gateway handoff policy.",
            },
            {
                "skill": "doctor",
                "purpose": "Verify the restored OMH/Hermes install after files and config are present.",
            },
            {
                "skill": "workflow-learning",
                "purpose": "Record missed routing or task-abstraction feedback without silently patching skills.",
            },
        ],
        "risk_domains": [
            "secrets",
            "duplicate_gateway_responders",
            "private_repo_exposure",
            "liveness_gap",
            "config_drift",
            "missing_runtime_observation",
        ],
        "evidence_boundary": {
            "prepared": "task card, inventory plan, package plan, restore checklist",
            "observed": [],
            "not_observed": [
                "encrypted backup archive",
                "private GitHub upload",
                "runtime restore on the second machine",
                "Hermes restart or plugin load",
                "gateway responder cutover",
                "liveness check after cutover",
            ],
            "degraded": [
                "missing credential inventory",
                "unverified target machine",
                "gateway ownership unknown",
            ],
        },
        "secret_policy": {
            "recommended_action": "encrypt before private GitHub upload",
            "never_package_by_default": [".env", "tokens", "API keys", "OAuth refresh tokens", "session cookies"],
            "if_user_proceeds": "record residual risk, rotate exposed credentials, and keep credential restore as observed-only evidence",
        },
        "gateway_transfer": {
            "invariant": "exactly_one_active_responder",
            "before_cutover": "disable or pause the old responder, then observe the new responder before claiming transfer complete",
            "duplicate_responder_risk": "two active gateways can answer the same user thread and corrupt state",
        },
        "liveness": {
            "prepared_checks": ["process or service presence", "Hermes response smoke", "gateway response smoke"],
            "degraded_until": "target machine and gateway response are observed after restore",
        },
        "first_safe_action": (
            "Inventory configs, local state, plugin paths, managed skills, gateways, and secret locations before packaging."
        ),
        "routing_reason": (
            "Matched runtime portability/environment reproduction signals; choose a task card first and use workflows as rails."
        ),
        "wrapper_guidance": (
            "Render this as a runtime portability task card. Show inventory, credential policy, restore, verify, "
            "gateway ownership transfer, and liveness risks before any workflow-specific action."
        ),
        "claim_boundary": (
            "This task card is prepared guidance only. It is not backup creation, private repo upload, restore, "
            "gateway cutover, liveness, verification, or completion evidence."
        ),
    }


def _maintenance_command_card(command: str) -> dict[str, object]:
    selected_skill = "doctor" if command == "doctor" else "oh-my-hermes"
    command_argv = ["omh", command]
    if command == "list":
        first_safe_action = "Run `omh list` and summarize the installed workflow catalog without starting repo work."
    else:
        first_safe_action = f"Run `omh {command}` and report only the observed maintenance output."
    return {
        "schema_version": TASK_CARD_SCHEMA_VERSION,
        "task_type": "omh_cli_maintenance",
        "route_level": TASK_CARD_MAINTENANCE_ROUTE_LEVEL,
        "confidence": "high",
        "score": 80,
        "selected_workflow_rail": selected_skill,
        "recommended_next_action": f"run_omh_{command}",
        "command": command,
        "command_argv": command_argv,
        "user_facing_summary": (
            f"I will run the OMH maintenance {command} path; code changes require a separate request."
        ),
        "not_a_workflow": [
            "coding_handoff",
            "router_design_feedback",
            "runtime_portability",
            "migration",
            "workflow_implementation",
        ],
        "operation_primitives": [
            "run_requested_command",
            "optional_health_check",
            "report_observed_output",
            "avoid_repo_mutation",
        ],
        "workflow_rails": [
            {
                "skill": selected_skill,
                "purpose": "Keep the response scoped to the requested OMH maintenance command and observed output.",
            },
            {
                "skill": "doctor",
                "purpose": "Use only when the requested command or follow-up health check needs install verification.",
            },
        ],
        "risk_domains": [
            "stale_context_inheritance",
            "over_execution",
            "unrequested_repo_mutation",
        ],
        "evidence_boundary": {
            "prepared": "operator maintenance command route and command argv",
            "observed": [],
            "not_observed": [
                f"`omh {command}` output",
                "doctor status after the command",
                "Hermes restart or plugin reload",
                "future Hermes chat/plugin runtime use",
            ],
            "degraded": [
                "command unavailable",
                "shell output missing",
                "maintenance command exits non-zero",
            ],
        },
        "first_safe_action": first_safe_action,
        "routing_reason": (
            "Matched a short OMH CLI maintenance command; route as operator maintenance before inheriting stale coding context."
        ),
        "wrapper_guidance": (
            "Render this as an operator maintenance command. Run the requested `omh` command, summarize observed output, "
            "and do not create branches, edit files, run implementation tests, or prepare coding handoffs unless the user asks separately."
        ),
        "claim_boundary": (
            "The maintenance route is prepared only. Only the requested command output and optional doctor status become observed evidence; "
            "Hermes reload, plugin runtime use, coding work, review, CI, and repository mutation remain unobserved unless separately verified."
        ),
    }


def _router_design_feedback_card() -> dict[str, object]:
    return {
        "schema_version": TASK_CARD_SCHEMA_VERSION,
        "task_type": "router_design_feedback",
        "route_level": TASK_CARD_ROUTE_LEVEL,
        "confidence": "high",
        "score": 55,
        "selected_workflow_rail": "workflow-learning",
        "recommended_next_action": "audit_learning_readiness",
        "user_facing_summary": (
            "This is workflow/router design feedback, not customer feedback triage."
        ),
        "not_a_workflow": ["customer_feedback_triage", "migration"],
        "operation_primitives": [
            "capture_trace",
            "classify_missed_route",
            "add_regression_case",
            "propose_router_patch",
            "human_review",
            "replay_regression",
        ],
        "workflow_rails": [
            {
                "skill": "workflow-learning",
                "purpose": "Record route feedback, evaluate the mistake, and prepare a reviewable improvement.",
            },
            {
                "skill": "oh-my-hermes",
                "purpose": "Keep the router mental model visible without forcing a shell command on chat users.",
            },
        ],
        "risk_domains": ["router_regression", "skill_drift", "unreviewed_self_patch", "customer_feedback_misroute"],
        "evidence_boundary": {
            "prepared": "task card, workflow-learning route, regression intent",
            "observed": [],
            "not_observed": [
                "raw prompt storage",
                "regression fixture added",
                "skill patch approved",
                "future behavior fixed",
            ],
            "degraded": ["missing minimized replay fixture"],
        },
        "first_safe_action": "Record a metadata-only workflow-learning trace and create a minimized regression case.",
        "routing_reason": (
            "Matched OMH routing/design feedback signals; route to workflow-learning before any domain-specific workflow."
        ),
        "wrapper_guidance": (
            "Treat this as router-design learning material. Do not route Korean or English OMH feedback to customer feedback triage."
        ),
        "claim_boundary": (
            "A workflow-learning task card is process-review evidence only. It is not a skill patch, model update, "
            "rerun, verification, CI, or proof that future routing is fixed."
        ),
    }
