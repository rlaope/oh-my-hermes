from __future__ import annotations

from ..wrapper.contract import VISIBLE_ACTIONS
from .schema import ORCHESTRATION_PATTERN_SCHEMA_VERSION, PREPARED_NOT_OBSERVED


def orchestration_patterns() -> list[dict[str, object]]:
    actions = set(VISIBLE_ACTIONS)
    return [
        _pattern(
            "single_lane",
            "Use for direct Hermes-retained work with one owner and one status lane.",
            "Do not use when parallel workers, executor sessions, or staged verification are required.",
            "guide",
            ("oh-my-hermes", "doctor", "web-research"),
            ("show_status",),
            actions,
            ("request_received", "response_prepared", "evidence_or_gap_reported"),
        ),
        _pattern(
            "clarify_then_plan",
            "Use when intent is fuzzy and a plan or accepted next action is needed before handoff.",
            "Do not use when the user explicitly invoked a concrete direct task.",
            "planner",
            ("deep-interview", "plan", "ralplan"),
            ("answer:clarify", "accept_plan", "revise_plan"),
            actions,
            ("clarification_answered", "plan_accepted", "handoff_prepared_or_declined"),
        ),
        _pattern(
            "plan_execute_verify",
            "Use when implementation or operational work needs a plan, execution owner, and verification gate.",
            "Do not treat the plan as observed execution.",
            "handoff-guide",
            ("ultragoal", "ultraprocess", "ralph"),
            ("prepare_handoff", "show_status", "ask_hermes_verify"),
            actions,
            ("plan_accepted", "execution_observed", "verification_observed"),
        ),
        _pattern(
            "fanout_synthesize",
            "Use when research, options, or evidence can be gathered in independent lanes and synthesized.",
            "Do not use when sources, tools, or authority boundaries are unclear.",
            "researcher",
            ("web-research", "research-brief", "strategy-brief"),
            ("show_status",),
            actions,
            ("sources_observed", "synthesis_prepared", "unknowns_reported"),
        ),
        _pattern(
            "adversarial_review",
            "Use when a verifier or reviewer should challenge a plan, output, or release claim.",
            "Do not call review passed until findings and required checks are observed.",
            "reviewer",
            ("code-review", "ultraqa", "ops-review"),
            ("ask_hermes_verify", "show_status", "prepare_handoff"),
            actions,
            ("review_requested", "findings_reported", "fix_or_approval_observed"),
        ),
        _pattern(
            "team_staged_pipeline",
            "Use for staged multi-lane work where lead/member/verifier ownership is explicit.",
            "Do not imply hidden workers ran; require worker_dispatch observations.",
            "handoff-guide",
            ("team", "ultrawork", "ultraprocess"),
            ("start_team", "start_swarm", "show_status"),
            actions,
            ("topology_prepared", "worker_dispatch_observed", "worker_result_observed"),
        ),
        _pattern(
            "swarm_batch",
            "Use for high-throughput batches only when lanes are independent and ownership is clear.",
            "Do not use for tightly coupled edits or unbounded scope.",
            "handoff-guide",
            ("ultrawork", "team"),
            ("start_swarm", "show_status"),
            actions,
            ("batch_prepared", "worker_dispatch_observed", "verification_observed"),
        ),
        _pattern(
            "worktree_isolated_workers",
            "Use when parallel implementation needs isolated working directories.",
            "Do not claim worktrees exist until runtime observation records them.",
            "handoff-guide",
            ("team", "ultrawork", "ultragoal"),
            ("prepare_worktree", "start_team", "show_status"),
            actions,
            ("worktree_policy_prepared", "worktree_creation_observed", "merge_readiness_observed"),
        ),
        _pattern(
            "loop_run_once",
            "Use when a loop should advance one bounded tick without a daemon or hidden execution.",
            "Do not use as a claim that automation, connectors, or subagents ran.",
            "planner",
            ("loop",),
            ("run_loop_tick", "show_loop_status", "prepare_loop_handoff"),
            actions,
            ("tick_prepared", "queue_item_prepared", "feedback_or_evidence_required"),
        ),
        _pattern(
            "scheduled_ops_blueprint",
            "Use when Hermes should prepare a recurring schedule, delivery, silence policy, and status card for an ops workflow.",
            "Do not claim host cron, Hermes automation, gateway delivery, source retrieval, no-agent execution, or plugin load from the blueprint.",
            "operator",
            ("automation-blueprint", "web-research", "research-brief", "report-package", "reliability-review"),
            ("show_status",),
            actions,
            ("blueprint_prepared", "host_schedule_observed", "delivery_observed", "source_retrieval_observed"),
        ),
        _pattern(
            "executor_session_handoff",
            "Use when Hermes prepares work for Codex, Claude Code, Hermes coding skills, or oh-my runtimes.",
            "Do not report completion before dispatch/result/verification evidence is recorded.",
            "handoff-guide",
            ("ultragoal", "ultrawork", "code-review", "ai-slop-cleaner"),
            ("choose_executor", "show_prompt_handoff", "show_runtime_handoff", "open_executor_session", "refresh_executor_status"),
            actions,
            ("handoff_prepared", "dispatch_observed", "result_observed", "verification_observed"),
        ),
        _pattern(
            "materials_generation_handoff",
            "Use when documents, decks, spreadsheets, PDFs, or other materials need generation/QA handoff.",
            "Do not claim binary export, render QA, formula recalculation, approval, or delivery without evidence.",
            "operator",
            ("materials-package", "report-package"),
            ("prepare_handoff", "show_status"),
            actions,
            ("material_plan_prepared", "generation_observed", "qa_observed"),
        ),
    ]


def _pattern(
    pattern_id: str,
    use_when: str,
    do_not_use_when: str,
    owner_role: str,
    compatible_skills: tuple[str, ...],
    required_actions: tuple[str, ...],
    available_actions: set[str],
    observed_evidence_required: tuple[str, ...],
) -> dict[str, object]:
    return {
        "schema_version": ORCHESTRATION_PATTERN_SCHEMA_VERSION,
        "id": pattern_id,
        "use_when": use_when,
        "do_not_use_when": do_not_use_when,
        "owner_role": owner_role,
        "compatible_skills": list(compatible_skills),
        "required_decisions": _required_decisions(pattern_id),
        "prepared_artifacts": _prepared_artifacts(pattern_id),
        "wrapper_actions": [action for action in required_actions if action in available_actions],
        "observed_evidence_required": list(observed_evidence_required),
        "status_card_copy": _status_copy(pattern_id),
        "prepared_is_not": PREPARED_NOT_OBSERVED,
        "source_refs": ["src/wrapper/contract.py", "src/skills/catalog.py", "src/runtime/records.py"],
    }


def _required_decisions(pattern_id: str) -> list[str]:
    if pattern_id in {"executor_session_handoff", "team_staged_pipeline", "swarm_batch", "worktree_isolated_workers"}:
        return ["executor_or_runtime_profile", "authority_scope", "verification_gate"]
    if pattern_id == "loop_run_once":
        return ["permission_profile", "next_verification", "feedback_or_wait_policy"]
    if pattern_id == "clarify_then_plan":
        return ["blocking_question", "accept_or_revise_plan"]
    return ["owner_role", "stop_condition"]


def _prepared_artifacts(pattern_id: str) -> list[str]:
    mapping = {
        "executor_session_handoff": ["coding_delegation/v1", "wrapper_session/v1"],
        "loop_run_once": ["loop_runtime/v1", "loop_status_card/v1"],
        "scheduled_ops_blueprint": ["hermes_ops_blueprint/v1"],
        "materials_generation_handoff": ["material_artifact/v1"],
        "worktree_isolated_workers": ["runtime_observation/v1 when observed"],
    }
    return mapping.get(pattern_id, ["chat_interaction/v1", "status_card/v1"])


def _status_copy(pattern_id: str) -> str:
    return f"Pattern `{pattern_id}` is prepared guidance until matching observed evidence is recorded."
