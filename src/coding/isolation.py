from __future__ import annotations


ISOLATION_SCHEMA_VERSION = "worktree_session_isolation/v1"

_HIGH_RISK_TERMS = (
    "architecture",
    "breaking",
    "generated",
    "large",
    "migration",
    "parallel",
    "refactor",
    "risky",
    "security",
    "swarm",
    "team",
    "worktree",
    "gefahr",
    "migracion",
    "paralelo",
    "riesgo",
    "seguridad",
    "risque",
    "securite",
    "parallele",
    "refactorisation",
    "sicherheit",
    "위험",
    "리팩터",
    "리팩토",
    "마이그레이션",
    "병렬",
    "스웜",
    "워크트리",
    "セキュリティ",
    "リファクタ",
    "危険",
    "移行",
    "並列",
    "安全",
    "并行",
    "重构",
    "風險",
    "风险",
)
_MEDIUM_RISK_TERMS = ("bug", "ci", "fix", "issue", "release", "review", "test")
_WORKTREE_REQUIRED_TERMS = ("parallel", "swarm", "team", "worktree", "병렬", "스웜", "워크트리", "並列", "并行")
_WORKTREE_RECOMMENDED_TERMS = (
    "breaking",
    "generated",
    "large",
    "migration",
    "refactor",
    "risky",
    "security",
    "gefahr",
    "riesgo",
    "seguridad",
    "risque",
    "securite",
    "sicherheit",
    "위험",
    "리팩터",
    "리팩토",
    "마이그레이션",
    "セキュリティ",
    "リファクタ",
    "危険",
    "移行",
    "安全",
    "重构",
    "風險",
    "风险",
)


def build_isolation_plan(
    message: str,
    *,
    intent: str,
    workflow: str,
    work_owner_mode: str,
    selected_executor_profile: str | None,
) -> dict[str, object]:
    lowered = message.lower()
    risk_level, reason_codes = _risk_level(lowered, intent=intent, workflow=workflow, work_owner_mode=work_owner_mode)
    strategy = _strategy(lowered, risk_level=risk_level, work_owner_mode=work_owner_mode, selected_executor_profile=selected_executor_profile)
    return {
        "schema_version": ISOLATION_SCHEMA_VERSION,
        "status": "prepared_not_observed",
        "strategy": strategy,
        "risk_level": risk_level,
        "reason_codes": reason_codes,
        "workspace_policy": _workspace_policy(strategy),
        "session_binding": "bind executor session to the current wrapper thread and selected workspace until observed otherwise",
        "required_before": _required_before(strategy),
        "recommended_when": [
            "multiple coding agents may edit the repository",
            "the change touches broad architecture, generated files, security, or migrations",
            "the wrapper will open a separate Codex, Claude Code, Hermes, or oh-my runtime session",
        ],
        "wrapper_actions": _wrapper_actions(strategy, work_owner_mode=work_owner_mode),
        "observation_events": [
            "executor_session/v1 open or attach records dispatch/open only",
            "runtime_observation/v1 worktree_creation records observed worktree creation when a runtime or wrapper sees it",
            "runtime_observation/v1 worker_dispatch records observed worker/team fanout when applicable",
        ],
        "not_observed_by_omh": [
            "git worktree creation",
            "branch creation",
            "executor process launch",
            "worker or subagent launch",
            "implementation, verification, review, CI, merge-readiness, or merge",
        ],
        "claim_boundary": (
            "This isolation plan is prepared guidance. It is not proof that a worktree, branch, executor session, "
            "worker, implementation, verification, review, CI, or merge exists."
        ),
    }


def _risk_level(lowered: str, *, intent: str, workflow: str, work_owner_mode: str) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if any(term in lowered for term in _HIGH_RISK_TERMS):
        reasons.append("high_risk_terms")
    if intent in {"cleanup", "diagnostics"}:
        reasons.append(f"intent:{intent}")
    if workflow in {"ai-slop-cleaner", "ultrawork", "team", "ralph", "ultragoal", "ultraprocess"}:
        reasons.append(f"workflow:{workflow}")
    if work_owner_mode == "runtime_handoff":
        reasons.append("runtime_handoff")
    if reasons:
        return "high", reasons
    if any(term in lowered for term in _MEDIUM_RISK_TERMS):
        return "medium", ["medium_risk_terms"]
    return "low", ["bounded_single_lane"]


def _strategy(
    lowered: str,
    *,
    risk_level: str,
    work_owner_mode: str,
    selected_executor_profile: str | None,
) -> str:
    if any(term in lowered for term in _WORKTREE_REQUIRED_TERMS):
        return "worktree_required"
    if work_owner_mode == "runtime_handoff" and selected_executor_profile not in {"hermes", None}:
        return "worktree_recommended"
    if any(term in lowered for term in _WORKTREE_RECOMMENDED_TERMS):
        return "worktree_recommended"
    if risk_level == "high":
        return "worktree_recommended"
    return "same_workspace_ok"


def _workspace_policy(strategy: str) -> str:
    if strategy == "worktree_required":
        return "open or attach the coding agent only after the wrapper/operator has prepared an isolated worktree"
    if strategy == "worktree_recommended":
        return "prefer an isolated worktree; reuse the current workspace only when the operator accepts the risk"
    return "reuse the current workspace unless later evidence shows parallel or risky edits"


def _required_before(strategy: str) -> list[str]:
    if strategy == "worktree_required":
        return ["open_executor_session", "worker_dispatch", "parallel_implementation"]
    if strategy == "worktree_recommended":
        return ["parallel_implementation", "risky_refactor", "team_or_swarm_coding"]
    return []


def _wrapper_actions(strategy: str, *, work_owner_mode: str) -> list[str]:
    actions = ["open_executor_session", "attach_executor_session", "show_status"]
    if strategy != "same_workspace_ok" or work_owner_mode == "runtime_handoff":
        actions.insert(0, "prepare_worktree")
    if work_owner_mode == "runtime_handoff":
        actions.append("record_runtime_observation")
    return actions
