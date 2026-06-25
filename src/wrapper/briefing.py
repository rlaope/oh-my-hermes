from __future__ import annotations

from typing import Any


CODING_BRIEFING_SCHEMA_VERSION = "coding_briefing/v1"


def build_coding_briefing(
    session: dict[str, Any],
    *,
    runtime_status: dict[str, Any] | None = None,
    executor_status: dict[str, Any] | None = None,
    runtime_observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic, user-facing summary from persisted wrapper evidence."""

    runtime_status = runtime_status if isinstance(runtime_status, dict) else {}
    executor_status = executor_status if isinstance(executor_status, dict) else {}
    runtime_observation = runtime_observation if isinstance(runtime_observation, dict) else {}

    session_id = str(session.get("session_id", ""))
    run_id = str(session.get("current_run_id") or runtime_status.get("run_id") or "")
    selected_executor = _selected_executor(session, runtime_status, executor_status)
    lifecycle_status = str(runtime_status.get("lifecycle_status") or _session_status_label(session))
    next_action = str(runtime_status.get("next_action") or _next_action_from_session(session, executor_status, runtime_observation))
    blocking_reason = str(runtime_status.get("blocking_reason") or _blocking_reason_from_status(next_action))
    progress = _progress_steps(session, runtime_status, executor_status, runtime_observation)
    runtime_milestones = _runtime_milestones(_active_handoff(session, runtime_status), runtime_observation)
    headline = _headline(selected_executor, lifecycle_status, next_action, executor_status, runtime_status, runtime_observation)
    evidence = _evidence_summary(progress, runtime_status, executor_status)
    pending_gaps = _pending_gaps(progress, runtime_status, executor_status, runtime_observation)
    work_summary = _work_summary(session, runtime_status)
    user_facing_lines = _user_facing_lines(
        headline=headline,
        executor_status=executor_status,
        work_summary=work_summary,
        runtime_milestones=runtime_milestones,
        pending_gaps=pending_gaps,
        next_action=next_action,
    )

    return {
        "schema_version": CODING_BRIEFING_SCHEMA_VERSION,
        "session_id": session_id,
        "run_id": run_id,
        "thread_key": str(session.get("thread_key", "")),
        "headline": headline,
        "narrative": _narrative(headline, pending_gaps, next_action),
        "current_state": {
            "session_status": str(session.get("status", "")),
            "selected_executor_profile": selected_executor,
            "coding_agent": _coding_agent_status(selected_executor, session, executor_status, runtime_observation),
            "lifecycle_status": lifecycle_status,
            "next_action": next_action,
            "blocking_reason": blocking_reason,
        },
        "original_context": _original_context(session, runtime_status),
        "work_summary": work_summary,
        "progress": progress,
        "runtime_milestones": runtime_milestones,
        "runtime_milestone_gaps": [str(step["id"]) for step in runtime_milestones if step.get("state") in {"pending", "blocked", "in_progress"}],
        "evidence_summary": evidence,
        "pending_gaps": pending_gaps,
        "next_action": next_action,
        "user_facing_lines": user_facing_lines,
        "claim_boundary": (
            "This briefing is derived from persisted wrapper/runtime artifacts only; "
            "prepared handoffs are not execution, verification, review, CI, or merge evidence."
        ),
    }


def chat_response_briefing(briefing: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": briefing.get("schema_version", CODING_BRIEFING_SCHEMA_VERSION),
        "headline": briefing.get("headline", ""),
        "lines": list(briefing.get("user_facing_lines", [])) if isinstance(briefing.get("user_facing_lines"), list) else [],
        "next_action": briefing.get("next_action", ""),
        "pending_gaps": list(briefing.get("pending_gaps", [])) if isinstance(briefing.get("pending_gaps"), list) else [],
        "claim_boundary": briefing.get("claim_boundary", ""),
    }


def _selected_executor(
    session: dict[str, Any],
    runtime_status: dict[str, Any],
    executor_status: dict[str, Any],
) -> str:
    prepared = _object(runtime_status.get("prepared"))
    return str(
        executor_status.get("selected_executor_profile")
        or session.get("selected_executor_profile")
        or prepared.get("executor_target")
        or "choose"
    )


def _session_status_label(session: dict[str, Any]) -> str:
    status = str(session.get("status", ""))
    if status in {"prompt_handoff_prepared", "runtime_handoff_prepared", "handoff_prepared"}:
        return "handoff_prepared"
    if status == "executor_choice_required":
        return "executor_choice_required"
    if status in {"plan_presented", "plan_accepted", "executor_selected"}:
        return "planning"
    return status or "unknown"


def _next_action_from_session(
    session: dict[str, Any],
    executor_status: dict[str, Any],
    runtime_observation: dict[str, Any],
) -> str:
    action = str(executor_status.get("next_action") or "")
    if action:
        return action
    observation_action = str(runtime_observation.get("next_action") or "")
    if observation_action and observation_action != "not_applicable":
        return observation_action
    return {
        "plan_presented": "accept_or_revise_plan",
        "plan_accepted": "prepare_handoff",
        "executor_choice_required": "choose_executor",
        "executor_selected": "prepare_handoff",
        "prompt_handoff_prepared": "show_prompt_handoff",
        "runtime_handoff_prepared": "show_runtime_handoff",
        "handoff_prepared": "show_status",
    }.get(str(session.get("status")), "show_status")


def _blocking_reason_from_status(next_action: str) -> str:
    if next_action in {"report_completion_with_evidence", "report_merge_ready", "report_merged", "show_status"}:
        return ""
    return f"{next_action} is required before this can be reported as complete"


def _headline(
    selected_executor: str,
    lifecycle_status: str,
    next_action: str,
    executor_status: dict[str, Any],
    runtime_status: dict[str, Any],
    runtime_observation: dict[str, Any],
) -> str:
    result = str(executor_status.get("result") or _object(runtime_status.get("execution")).get("status") or "not_observed")
    verification = str(executor_status.get("verification") or ("observed" if _object(runtime_status.get("verification")).get("observed") else "not_observed"))
    runtime_result_observed = _runtime_event_observed(runtime_observation, "worker_result")
    runtime_verification_observed = _runtime_event_observed(runtime_observation, "verification")
    if _runtime_event_observed(runtime_observation, "merge"):
        return f"{_label(selected_executor)} work is recorded as merged."
    if _runtime_event_observed(runtime_observation, "merge_readiness"):
        return f"{_label(selected_executor)} work is merge-ready with recorded evidence."
    if runtime_result_observed and not runtime_verification_observed:
        return f"{_label(selected_executor)} reported completion; verification evidence is still needed."
    if runtime_result_observed and runtime_verification_observed:
        return f"{_label(selected_executor)} result and verification are observed."
    if result == "completed" and verification not in {"observed", "satisfied"}:
        return f"{_label(selected_executor)} reported completion; verification evidence is still needed."
    if lifecycle_status == "merge_ready" or next_action == "report_merge_ready":
        return f"{_label(selected_executor)} work is merge-ready with recorded evidence."
    if lifecycle_status == "merged" or next_action == "report_merged":
        return f"{_label(selected_executor)} work is recorded as merged."
    if str(executor_status.get("dispatch")) == "observed":
        return f"{_label(selected_executor)} is handling the coding work."
    if selected_executor == "choose":
        return "Hermes is waiting for a coding-agent choice."
    return f"{_label(selected_executor)} handoff is prepared."


def _original_context(session: dict[str, Any], runtime_status: dict[str, Any]) -> dict[str, Any]:
    route = _object(session.get("route"))
    plan = _object(session.get("plan"))
    prepared = _object(runtime_status.get("prepared"))
    return {
        "source": str(session.get("source", "")),
        "source_metadata": _string_map(session.get("source_metadata")),
        "message": {
            "sha256": str(session.get("message_sha256", "")),
            "length": int(session.get("message_length", 0) or 0),
            "raw_text_persisted": False,
        },
        "route": {
            "selected_skill": str(route.get("selected_skill", "")),
            "selected_harness": str(route.get("selected_harness", "")),
            "confidence": str(route.get("confidence", "")),
            "score": int(route.get("score", 0) or 0),
            "reason": str(route.get("reason", "")),
        },
        "plan": {
            "status": str(plan.get("status", "")),
            "recommended_workflow": str(plan.get("recommended_workflow") or prepared.get("workflow") or ""),
            "recommended_harness": str(plan.get("recommended_harness") or prepared.get("harness") or ""),
            "coding_delegate_available": str(plan.get("coding_delegate_available", "")),
        },
        "deep_interview": {
            "persisted": False,
            "reason": "wrapper sessions persist compact route/plan metadata, not a full interview transcript",
        },
    }


def _work_summary(session: dict[str, Any], runtime_status: dict[str, Any]) -> dict[str, Any]:
    handoff = _active_handoff(session, runtime_status)
    prepared = _object(runtime_status.get("prepared"))
    review = _object(handoff.get("review") or runtime_status.get("review"))
    return {
        "workflow": str(prepared.get("workflow") or _object(session.get("plan")).get("recommended_workflow") or handoff.get("recommended_workflow") or ""),
        "harness": str(prepared.get("harness") or _object(session.get("plan")).get("recommended_harness") or handoff.get("recommended_harness") or ""),
        "executor": str(handoff.get("selected_executor_profile") or prepared.get("executor_target") or session.get("selected_executor_profile") or "choose"),
        "work_owner_mode": str(session.get("work_owner_mode", "")),
        "handoff_schema_version": str(handoff.get("schema_version") or prepared.get("handoff_schema_version") or ""),
        "safe_summary": str(runtime_status.get("safe_summary") or _handoff_summary(session, handoff)),
        "acceptance_criteria": _string_list(handoff.get("acceptance_criteria")),
        "verification_expected": _string_list(handoff.get("verification") or _object(runtime_status.get("verification")).get("expected")),
        "handoff_contract": {
            "execution_brief": _object(handoff.get("execution_brief")),
            "runtime_brief": _object(handoff.get("runtime_brief")),
            "isolation_plan": _isolation_plan_summary(_object(handoff.get("isolation_plan"))),
            "report_contract": _object(handoff.get("report_contract")),
            "evidence_contract": _object(handoff.get("evidence_contract")),
            "coding_team_path": _coding_team_path_summary(_object(handoff.get("hermes_coding_team_path"))),
            "context_pack": _context_pack_summary(_object(handoff.get("context_pack"))),
            "context_pack_blocked": _context_pack_blocked_summary(_object(handoff.get("context_pack_blocked"))),
            "memory_recall_pack": _memory_recall_pack_summary(_object(handoff.get("memory_recall_pack"))),
        },
        "review": {
            "required": bool(review.get("required", False)),
            "workflow": str(review.get("workflow") or ""),
            "status": str(review.get("status") or ""),
        },
    }


def _active_handoff(session: dict[str, Any], runtime_status: dict[str, Any]) -> dict[str, Any]:
    handoff_contract = _object(runtime_status.get("handoff_contract"))
    if handoff_contract:
        return handoff_contract
    for key in ("prompt_handoff", "runtime_handoff"):
        handoff = _object(session.get(key))
        if handoff:
            return handoff
    prepared = _object(runtime_status.get("prepared"))
    if prepared:
        # Runtime status is compact; the session keeps richer prompt/runtime handoff detail for non-run paths.
        return {
            "schema_version": prepared.get("handoff_schema_version", ""),
            "selected_executor_profile": prepared.get("executor_target", ""),
            "recommended_workflow": prepared.get("workflow", ""),
            "recommended_harness": prepared.get("harness", ""),
        }
    return {}


def _handoff_summary(session: dict[str, Any], handoff: dict[str, Any]) -> str:
    status = str(session.get("status", ""))
    selected = str(handoff.get("selected_executor_profile") or session.get("selected_executor_profile") or "executor")
    if status == "prompt_handoff_prepared":
        return f"A prompt-only handoff for {selected} is prepared; no dispatch or execution is observed."
    if status == "runtime_handoff_prepared":
        return f"A runtime handoff for {selected} is prepared; runtime activity is not observed unless recorded separately."
    if status == "executor_choice_required":
        return "The plan is accepted, but no coding-agent has been selected."
    return "The wrapper session has not observed execution evidence."


def _progress_steps(
    session: dict[str, Any],
    runtime_status: dict[str, Any],
    executor_status: dict[str, Any],
    runtime_observation: dict[str, Any],
) -> list[dict[str, Any]]:
    handoff_prepared = _handoff_prepared(session, runtime_status, executor_status)
    isolation_status = _object(executor_status.get("workspace_isolation"))
    dispatch_observed = _bool_path(runtime_status, "execution", "observed") or str(executor_status.get("dispatch")) == "observed"
    result = str(executor_status.get("result") or _object(runtime_status.get("execution")).get("status") or "not_observed")
    result_observed = result in {"completed", "blocked", "failed"}
    verification_observed = bool(_object(runtime_status.get("verification")).get("observed")) or str(executor_status.get("verification")) in {
        "observed",
        "satisfied",
    }
    verification_requested = str(executor_status.get("verification")) == "requested"
    review = _object(runtime_status.get("review"))
    ci = _object(runtime_status.get("ci"))
    merge_readiness = _object(runtime_status.get("merge_readiness"))
    merge = _object(runtime_status.get("merge"))
    runtime_started = _runtime_event_observed(runtime_observation, "runtime_start") or _runtime_event_observed(
        runtime_observation, "worker_dispatch"
    )
    runtime_result_observed = _runtime_event_observed(runtime_observation, "worker_result")
    runtime_verification_observed = _runtime_event_observed(runtime_observation, "verification")
    result_summary = "completed" if runtime_result_observed and result == "not_observed" else result
    verification_state = "complete" if verification_observed or runtime_verification_observed else (
        "in_progress" if verification_requested else ("pending" if result_observed or runtime_result_observed else "blocked")
    )
    verification_state = _runtime_event_state(runtime_observation, "verification", verification_state)
    return [
        _step("plan", "Plan", _state(bool(session.get("plan")), False), "Compact route and plan metadata are recorded."),
        _step("handoff", "Handoff", _state(handoff_prepared, False), "A coding-agent handoff is prepared."),
        _step(
            "workspace_isolation",
            "Workspace isolation",
            _workspace_isolation_state(isolation_status, runtime_observation),
            "Worktree/session isolation guidance is prepared separately from observed worktree creation.",
        ),
        _step(
            "dispatch",
            "Dispatch",
            _runtime_event_state(runtime_observation, "runtime_start", _state(dispatch_observed or runtime_started, handoff_prepared)),
            "Wrapper/runtime dispatch or start evidence is observed.",
        ),
        _step(
            "executor_result",
            "Executor result",
            _runtime_event_state(runtime_observation, "worker_result", _state(result_observed or runtime_result_observed, dispatch_observed or runtime_started)),
            f"Executor result: {result_summary}.",
        ),
        _step(
            "verification",
            "Verification",
            verification_state,
            "Hermes verification request or observed verification evidence.",
        ),
        _step(
            "review",
            "Review",
            _runtime_event_state(runtime_observation, "review", _record_state(review, complete_statuses={"passed"})),
            "Review evidence recorded separately.",
        ),
        _step(
            "ci",
            "CI",
            _runtime_event_state(runtime_observation, "ci", _record_state(ci, complete_statuses={"passed"})),
            "CI evidence recorded separately.",
        ),
        _step(
            "merge_ready",
            "Merge ready",
            _runtime_event_state(runtime_observation, "merge_readiness", _record_state(merge_readiness, complete_statuses={"ready", "merged"})),
            "Merge readiness evidence recorded separately.",
        ),
        _step("merged", "Merged", _runtime_event_state(runtime_observation, "merge", _merged_state(merge)), "Merge evidence recorded separately."),
    ]


def _evidence_summary(
    progress: list[dict[str, Any]],
    runtime_status: dict[str, Any],
    executor_status: dict[str, Any],
) -> dict[str, Any]:
    observed = [str(step["id"]) for step in progress if step.get("state") == "complete"]
    not_observed = [str(step["id"]) for step in progress if step.get("state") in {"pending", "blocked", "in_progress"}]
    refs: list[str] = []
    for value in (
        _object(runtime_status.get("execution")).get("evidence_refs"),
        _object(runtime_status.get("review")).get("evidence_refs"),
        _object(runtime_status.get("ci")).get("evidence_refs"),
        _object(runtime_status.get("merge")).get("evidence_refs"),
        executor_status.get("evidence_refs"),
    ):
        refs.extend(_string_list(value))
    return {
        "observed": observed,
        "not_observed": not_observed,
        "evidence_refs": _dedupe(refs),
    }


def _pending_gaps(
    progress: list[dict[str, Any]],
    runtime_status: dict[str, Any],
    executor_status: dict[str, Any],
    runtime_observation: dict[str, Any],
) -> list[str]:
    gaps = [str(step["id"]) for step in progress if step.get("state") in {"pending", "blocked", "in_progress"} and str(step.get("id")) != "plan"]
    wrapper = _object(runtime_status.get("wrapper"))
    gaps.extend(_string_list(wrapper.get("unobserved_gaps")))
    if executor_status.get("executor_session_error"):
        gaps.append("executor_session_error")
    if runtime_observation.get("errors"):
        gaps.append("runtime_observation_errors")
    return _dedupe(gaps)


def _user_facing_lines(
    *,
    headline: str,
    executor_status: dict[str, Any],
    work_summary: dict[str, Any],
    runtime_milestones: list[dict[str, str]],
    pending_gaps: list[str],
    next_action: str,
) -> list[str]:
    lines = [headline]
    display = executor_status.get("display_status_lines")
    if isinstance(display, list):
        lines.extend(str(line) for line in display[:4] if str(line))
    safe_summary = str(work_summary.get("safe_summary", ""))
    if safe_summary and safe_summary not in lines:
        lines.append(safe_summary)
    team_path = _object(_object(work_summary.get("handoff_contract")).get("coding_team_path"))
    isolation_plan = _object(_object(work_summary.get("handoff_contract")).get("isolation_plan"))
    if isolation_plan:
        strategy = str(isolation_plan.get("strategy", "same_workspace_ok"))
        if strategy == "worktree_required":
            lines.append("Workspace isolation is required before starting the coding session.")
        elif strategy == "worktree_recommended":
            lines.append("Workspace isolation is recommended before starting the coding session.")
    if team_path:
        observed = [str(step["id"]) for step in runtime_milestones if step.get("state") == "complete"]
        remaining = [str(step["id"]) for step in runtime_milestones if step.get("state") in {"pending", "blocked", "in_progress"}]
        if observed:
            lines.append(
                "Hermes coding team path observations: "
                f"{', '.join(observed[:4])}; still missing: {', '.join(remaining[:5]) or 'none'}."
            )
        else:
            lines.append(
                "Hermes coding team path is prepared; runtime observations are still required before "
                "worker, worktree, verification, review, CI, or merge claims advance."
            )
    if pending_gaps:
        lines.append(f"Still missing evidence: {', '.join(pending_gaps[:5])}.")
    lines.append(f"Next action: {next_action}.")
    return _dedupe(lines)


def _narrative(headline: str, pending_gaps: list[str], next_action: str) -> str:
    if pending_gaps:
        return f"{headline} The wrapper is still waiting on {', '.join(pending_gaps[:4])}; next action is {next_action}."
    return f"{headline} The wrapper has no additional pending gap in this briefing; next action is {next_action}."


def _handoff_prepared(session: dict[str, Any], runtime_status: dict[str, Any], executor_status: dict[str, Any]) -> bool:
    prepared = _object(runtime_status.get("prepared"))
    return (
        bool(prepared.get("handoff_available"))
        or str(executor_status.get("handoff")) == "prepared"
        or str(session.get("status")) in {"handoff_prepared", "prompt_handoff_prepared", "runtime_handoff_prepared"}
    )


def _record_state(record: dict[str, Any], *, complete_statuses: set[str]) -> str:
    if not record:
        return "pending"
    status = str(record.get("status", ""))
    if status == "not_required" and not bool(record.get("required", False)):
        return "not_required"
    if status in complete_statuses and (bool(record.get("satisfied")) or bool(record.get("observed"))):
        return "complete"
    if bool(record.get("observed")):
        return "in_progress"
    if bool(record.get("required")):
        return "pending"
    return "pending"


def _merged_state(record: dict[str, Any]) -> str:
    if not record:
        return "pending"
    if str(record.get("status", "")) == "not_required" and not bool(record.get("required", False)):
        return "not_required"
    return "complete" if str(record.get("status", "")) == "merged" and bool(record.get("satisfied")) else "pending"


def _context_pack_summary(context_pack: dict[str, Any]) -> dict[str, Any]:
    if not context_pack:
        return {}
    if "included_context_count" in context_pack:
        return {
            "schema_version": str(context_pack.get("schema_version", "")),
            "executor_target": str(context_pack.get("executor_target", "")),
            "session_id": str(context_pack.get("session_id", "")),
            "source_ref_count": int(context_pack.get("source_ref_count", 0) or 0),
            "included_context_count": int(context_pack.get("included_context_count", 0) or 0),
            "excluded_context_count": int(context_pack.get("excluded_context_count", 0) or 0),
            "blocked_by_conflicts_count": int(context_pack.get("blocked_by_conflicts_count", 0) or 0),
            "redaction_policy": str(context_pack.get("redaction_policy", "")),
            "claim_boundary": str(context_pack.get("claim_boundary", "")),
        }
    return {
        "schema_version": str(context_pack.get("schema_version", "")),
        "executor_target": str(context_pack.get("executor_target", "")),
        "session_id": str(context_pack.get("session_id", "")),
        "source_ref_count": len(_list_value(context_pack.get("source_refs"))),
        "included_context_count": len(_list_value(context_pack.get("included_context"))),
        "excluded_context_count": len(_list_value(context_pack.get("excluded_context"))),
        "blocked_by_conflicts_count": len(_list_value(context_pack.get("blocked_by_conflicts"))),
        "redaction_policy": str(context_pack.get("redaction_policy", "")),
        "claim_boundary": str(context_pack.get("claim_boundary", "")),
    }


def _memory_recall_pack_summary(memory_recall_pack: dict[str, Any]) -> dict[str, Any]:
    if not memory_recall_pack:
        return {}
    if "record_count" in memory_recall_pack and "included_records" not in memory_recall_pack:
        return {
            "schema_version": str(memory_recall_pack.get("schema_version", "")),
            "executor_target": str(memory_recall_pack.get("executor_target", "")),
            "session_id": str(memory_recall_pack.get("session_id", "")),
            "record_count": int(memory_recall_pack.get("record_count", 0) or 0),
            "excluded_count": int(memory_recall_pack.get("excluded_count", 0) or 0),
            "redaction_policy": str(memory_recall_pack.get("redaction_policy", "")),
            "claim_boundary": str(memory_recall_pack.get("claim_boundary", "")),
        }
    return {
        "schema_version": str(memory_recall_pack.get("schema_version", "")),
        "executor_target": str(memory_recall_pack.get("executor_target", "")),
        "session_id": str(memory_recall_pack.get("session_id", "")),
        "record_count": len(_list_value(memory_recall_pack.get("included_records"))),
        "excluded_count": len(_list_value(memory_recall_pack.get("excluded_records"))),
        "redaction_policy": str(memory_recall_pack.get("redaction_policy", "")),
        "claim_boundary": str(memory_recall_pack.get("claim_boundary", "")),
    }


def _isolation_plan_summary(plan: dict[str, Any]) -> dict[str, Any]:
    if not plan:
        return {}
    return {
        "schema_version": str(plan.get("schema_version", "")),
        "status": str(plan.get("status", "")),
        "strategy": str(plan.get("strategy", "")),
        "risk_level": str(plan.get("risk_level", "")),
        "workspace_policy": str(plan.get("workspace_policy", "")),
        "required_before": _string_list(plan.get("required_before")),
        "wrapper_actions": _string_list(plan.get("wrapper_actions")),
        "claim_boundary": str(plan.get("claim_boundary", "")),
    }


def _coding_team_path_summary(path: dict[str, Any]) -> dict[str, Any]:
    if not path:
        return {}
    return {
        "schema_version": str(path.get("schema_version", "")),
        "status": str(path.get("status", "")),
        "start_modes": [
            {
                "id": str(mode.get("id", "")),
                "label": str(mode.get("label", "")),
                "entrypoint": str(mode.get("entrypoint", "")),
                "first_observed_event": str(mode.get("first_observed_event", "")),
            }
            for mode in _list_value(path.get("start_modes"))
            if isinstance(mode, dict)
        ],
        "status_ladder": _string_list(path.get("status_ladder")),
        "wrapper_actions": _string_list(path.get("wrapper_actions")),
        "claim_boundary": str(path.get("claim_boundary", "")),
    }


def _runtime_milestones(handoff: dict[str, Any], runtime_observation: dict[str, Any]) -> list[dict[str, str]]:
    team_path = _object(handoff.get("hermes_coding_team_path"))
    observation_contract = _object(handoff.get("observation_contract"))
    ladder = _string_list(team_path.get("status_ladder")) or _string_list(observation_contract.get("status_ladder"))
    if not ladder:
        return []
    return [
        {
            "id": event_type,
            "state": _runtime_event_state(runtime_observation, event_type, "pending"),
            "summary": _runtime_milestone_summary(event_type),
        }
        for event_type in ladder
    ]


def _runtime_milestone_summary(event_type: str) -> str:
    summaries = {
        "runtime_start": "The selected runtime or Hermes coding path has actually started.",
        "worktree_creation": "An isolated worktree or equivalent workspace has been observed.",
        "worker_dispatch": "A worker lane, team member, or equivalent runtime lane has been dispatched.",
        "worker_result": "A worker or runtime lane reported a result with metadata.",
        "verification": "Verification evidence has been recorded separately.",
        "review": "Review evidence has been recorded separately.",
        "ci": "CI evidence has been recorded separately.",
        "merge_readiness": "Merge readiness has been recorded separately.",
        "merge": "Merge evidence has been recorded separately.",
    }
    return summaries.get(event_type, f"{event_type} evidence has been recorded separately.")


def _context_pack_blocked_summary(context_pack_blocked: dict[str, Any]) -> dict[str, Any]:
    if not context_pack_blocked:
        return {}
    if "blocked_by_conflicts_count" in context_pack_blocked:
        return {
            "schema_version": str(context_pack_blocked.get("schema_version", "")),
            "blocked_by_conflicts_count": int(context_pack_blocked.get("blocked_by_conflicts_count", 0) or 0),
            "claim_boundary": str(context_pack_blocked.get("claim_boundary", "")),
        }
    return {
        "schema_version": str(context_pack_blocked.get("schema_version", "")),
        "blocked_by_conflicts_count": len(_list_value(context_pack_blocked.get("blocked_by_conflicts"))),
        "claim_boundary": str(context_pack_blocked.get("claim_boundary", "")),
    }


def _runtime_event_state(runtime_observation: dict[str, Any], event_type: str, default_state: str) -> str:
    if _runtime_event_failed_or_blocked(runtime_observation, event_type):
        return "blocked"
    if _runtime_event_observed(runtime_observation, event_type):
        return "complete"
    return default_state


def _runtime_event_observed(runtime_observation: dict[str, Any], event_type: str) -> bool:
    return event_type in _string_list(runtime_observation.get("observed_events"))


def _runtime_event_failed_or_blocked(runtime_observation: dict[str, Any], event_type: str) -> bool:
    return event_type in set(_string_list(runtime_observation.get("failed_events")) + _string_list(runtime_observation.get("blocked_events")))


def _workspace_isolation_state(isolation_status: dict[str, Any], runtime_observation: dict[str, Any]) -> str:
    if _runtime_event_failed_or_blocked(runtime_observation, "worktree_creation"):
        return "blocked"
    if _runtime_event_observed(runtime_observation, "worktree_creation"):
        return "complete"
    status = str(isolation_status.get("status", "not_applicable"))
    if status in {"observed", "not_required"}:
        return "complete"
    if status == "prepared_not_observed":
        return "pending"
    return "pending"


def _state(done: bool, available: bool) -> str:
    if done:
        return "complete"
    return "pending" if available else "blocked"


def _step(step_id: str, label: str, state: str, summary: str) -> dict[str, str]:
    return {"id": step_id, "label": label, "state": state, "summary": summary}


def _coding_agent_label(selected_executor: str, session: dict[str, Any]) -> str:
    status = str(session.get("status", ""))
    if status in {"handoff_prepared", "prompt_handoff_prepared", "runtime_handoff_prepared"}:
        return f"prepared({selected_executor})"
    return f"idle({selected_executor})"


def _coding_agent_status(
    selected_executor: str,
    session: dict[str, Any],
    executor_status: dict[str, Any],
    runtime_observation: dict[str, Any],
) -> str:
    if _runtime_event_failed_or_blocked(runtime_observation, "worker_result"):
        return f"blocked({selected_executor})"
    if _runtime_event_observed(runtime_observation, "worker_result"):
        return f"completed({selected_executor})"
    if _runtime_event_observed(runtime_observation, "runtime_start") or _runtime_event_observed(runtime_observation, "worker_dispatch"):
        return f"running({selected_executor})"
    return str(executor_status.get("coding_agent") or _coding_agent_label(selected_executor, session))


def _bool_path(source: dict[str, Any], *path: str) -> bool:
    current: Any = source
    for key in path:
        current = current.get(key) if isinstance(current, dict) else None
    return bool(current)


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _string_map(value: Any) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items() if str(item)}


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _label(profile: str) -> str:
    labels = {
        "codex": "Codex",
        "claude-code": "Claude Code",
        "omx-runtime": "OMX runtime",
        "omo-runtime": "OMO runtime",
        "omc-runtime": "OMC runtime",
        "hermes": "Hermes",
        "generic": "the selected coding agent",
        "choose": "Hermes",
    }
    return labels.get(profile, profile or "the selected coding agent")
