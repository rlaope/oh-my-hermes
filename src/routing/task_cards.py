from __future__ import annotations

from .localization import normalized_phrase, routing_tokens


TASK_CARD_SCHEMA_VERSION = "omh_task_card/v1"
TASK_CARD_ROUTE_LEVEL = "task_abstraction"

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
    "omh 관여",
    "얼마나 관여",
)

def classify_task(message: str) -> dict[str, object] | None:
    """Classify high-level user tasks before choosing lower-level workflow rails."""
    normalized = normalized_phrase(message)
    compact = normalized.replace(" ", "")
    tokens = set(routing_tokens(message, stopwords=set()))
    tokens.update(normalized.split())

    if _is_router_design_feedback(normalized, compact, tokens):
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
        "matched": [f"task_card:{task_type}", "task_abstraction"],
        "next_action": str(card.get("recommended_next_action", "show_workflow_guidance")),
        "evidence_boundary": str(card.get("claim_boundary", "")),
        "wrapper_guidance": str(card.get("wrapper_guidance", "")),
        "why": str(card.get("routing_reason", "Matched high-level task abstraction before workflow routing.")),
    }


def _is_runtime_portability(normalized: str, compact: str, tokens: set[str]) -> bool:
    phrase_hit = _phrase_hit(_RUNTIME_PORTABILITY_PHRASES, normalized, compact)
    if not phrase_hit:
        return False
    context_hits = len(tokens & _RUNTIME_CONTEXT_NORMALIZED_TOKENS)
    if context_hits:
        return True
    return _phrase_hit(("gateway", "bot", "responder", "게이트웨이", "봇", "응답자"), normalized, compact)


def _is_router_design_feedback(normalized: str, compact: str, tokens: set[str]) -> bool:
    phrase_hit = _phrase_hit(_ROUTER_DESIGN_CONTEXT_PHRASES, normalized, compact)
    if phrase_hit:
        return True
    if (
        _phrase_hit(("피드백",), normalized, compact)
        and "omh" in normalized
        and _phrase_hit(("라우팅", "라우터", "워크플로", "워크플로우", "설계", "추상화"), normalized, compact)
    ):
        return True
    return False


def _phrase_hit(phrases: tuple[str, ...], normalized: str, compact: str) -> bool:
    for phrase in phrases:
        normalized_phrase_value = normalized_phrase(phrase)
        if normalized_phrase_value and (
            normalized_phrase_value in normalized or normalized_phrase_value.replace(" ", "") in compact
        ):
            return True
    return False


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
