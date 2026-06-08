from __future__ import annotations

import hashlib
from typing import Any

from ..ingress import CHAT_SOURCES, compact_source_metadata, extract_message_text, extract_source_metadata
from ..routing.chat import public_route_payload, route_chat_message
from ..coding_delegation import build_coding_delegation_payload
from ..executors import executor_label
from ..hermes_planning import build_hermes_plan_payload
from ..skills.catalog import retained_delegation_skill_names


CHAT_INTERACTION_SCHEMA_VERSION = "chat_interaction/v1"
CHAT_RESPONSE_SCHEMA_VERSION = "chat_response/v1"
STATUS_CARD_SCHEMA_VERSION = "status_card/v1"
INTERACTION_MODES = ("auto", "route", "plan", "delegate")
VISIBLE_ACTIONS = (
    "answer:clarify",
    "accept_plan",
    "revise_plan",
    "prepare_handoff",
    "choose_executor",
    "show_prompt_handoff",
    "copy_prompt_handoff",
    "send_to_executor",
    "send_to_codex",
    "show_status",
    "show_target_status",
    "apply_target_change",
    "cancel",
)
_ROUTE_TO_MODE = {"dispatch": "plan", "clarify": "clarify", "fallback": "clarify"}
_CLARIFICATION_SKILLS = {"deep-interview"}
_RETAINED_DELEGATION_SKILLS = set(retained_delegation_skill_names())
_DIRECT_WORKFLOW_SKILLS = {
    "web-research",
    "ultraqa",
    "code-review",
    "best-practice-research",
    "autoresearch-goal",
    "doctor",
    "skill",
    "wiki",
    *_RETAINED_DELEGATION_SKILLS,
} - (_CLARIFICATION_SKILLS | {"cancel"})
_STATUS_COPY = {
    "prepare_coding_delegation": (
        "handoff",
        "I am preparing the handoff details.",
        "No executor work is observed yet.",
        "No execution has started.",
    ),
    "clarify_coding_request": (
        "clarification",
        "I need one clarification before delegation.",
        "I will keep this in the chat until the task is specific enough.",
        "No execution has started.",
    ),
    "route_coding_request": (
        "clarification",
        "I need to route this before delegation.",
        "I will ask for the missing outcome before sending anything to an executor.",
        "No execution has started.",
    ),
    "dispatch_to_executor": (
        "handoff",
        "An executor handoff is ready.",
        "I have prepared the handoff, but executor dispatch is not observed yet.",
        "Preparation is not execution evidence.",
    ),
    "wait_for_executor_evidence": (
        "status",
        "The handoff was dispatched.",
        "I am waiting for executor evidence before reporting completion.",
        "Dispatch is not completion evidence.",
    ),
    "surface_executor_blocker": (
        "blocker",
        "The executor reported a blocker.",
        "I will surface the blocker instead of claiming completion.",
        "Blocked executor work is not complete.",
    ),
    "record_review_evidence": (
        "status",
        "Executor completion needs review evidence.",
        "I will not report completion until review evidence is observed.",
        "Execution is observed; review is not.",
    ),
    "surface_review_blocker": (
        "blocker",
        "Review is blocking completion.",
        "I will surface the review blocker instead of claiming completion.",
        "Review did not pass.",
    ),
    "record_verification_evidence": (
        "status",
        "Executor completion needs verification evidence.",
        "I will not report completion until verification evidence is observed.",
        "Execution is observed; verification is not.",
    ),
    "record_ci_evidence": (
        "status",
        "Review passed; CI evidence is still missing.",
        "I will not report merge readiness until CI evidence is observed.",
        "Review is not CI evidence.",
    ),
    "surface_ci_blocker": (
        "blocker",
        "CI is blocking completion.",
        "I will surface the failing or blocked CI checks instead of claiming merge readiness.",
        "Failed CI is not merge-ready.",
    ),
    "record_merge_readiness": (
        "status",
        "Review and CI passed; merge readiness is still missing.",
        "I will not report merge-ready until merge readiness evidence is observed.",
        "CI passing is not merge evidence.",
    ),
    "surface_merge_blocker": (
        "blocker",
        "Merge is blocked.",
        "I will surface the merge blocker instead of claiming the run is ready.",
        "Blocked merge is not complete.",
    ),
    "report_completion_with_evidence": (
        "status",
        "Executor completion is reportable.",
        "Execution and verification evidence are observed.",
        "Completion is backed by observed wrapper evidence.",
    ),
    "report_merge_ready": (
        "status",
        "This is ready to merge.",
        "Execution, verification, review, CI, and merge-readiness evidence are observed.",
        "Ready to merge is not the same as merged.",
    ),
    "report_merged": (
        "status",
        "This has been merged.",
        "Execution, verification, review, CI, and merge evidence are observed.",
        "Merged status is backed by runtime ledger evidence.",
    ),
}


def build_chat_interaction_payload(
    event_or_message: dict[str, Any] | str,
    *,
    source: str = "generic",
    mode: str = "auto",
    limit: int = 3,
    min_confidence: str = "high",
    include_message: bool = False,
    executor_target: str = "choose",
    source_metadata: dict[str, str] | None = None,
    target_notice: dict[str, object] | None = None,
) -> dict[str, object]:
    if source not in CHAT_SOURCES:
        raise ValueError(f"unsupported chat interaction source: {source}")
    if mode not in INTERACTION_MODES:
        raise ValueError(f"unsupported chat interaction mode: {mode}")
    if limit < 1:
        raise ValueError("chat interact --limit must be at least 1")

    message = extract_message_text(event_or_message)
    metadata = _source_metadata(event_or_message, source_metadata)
    route = route_chat_message(message, source=source, limit=limit, min_confidence=min_confidence)
    resolved_mode = _resolve_mode(mode, route)
    base = _base_interaction(message, source=source, source_metadata=metadata, mode=resolved_mode, include_message=include_message)
    base["route"] = public_route_payload(route, include_message=include_message)

    if resolved_mode == "clarify" or route["action"] != "dispatch":
        base["next_action"] = "answer_clarification"
        base["chat_response"] = build_chat_response_from_route(route, thread_key=str(base["thread_key"]))
        return _finish_interaction(base, target_notice)

    if resolved_mode == "route":
        base["chat_response"] = build_chat_response_from_route(route, thread_key=str(base["thread_key"]))
        base["next_action"] = str(_nested(base["chat_response"], "state").get("next_action", "dispatch_to_workflow"))
        return _finish_interaction(base, target_notice)

    if resolved_mode == "delegate":
        delegation = build_coding_delegation_payload(
            message,
            source=source,
            limit=limit,
            include_message=include_message,
            source_metadata=metadata,
            executor_target=executor_target,
        )
        base["delegation"] = delegation
        action = str(_nested(delegation, "delegation").get("action", "fallback"))
        if action == "delegate" and delegation.get("executor_handoff"):
            base["next_action"] = "send_to_executor"
        elif action == "delegate" and delegation.get("prompt_handoff"):
            base["next_action"] = "show_prompt_handoff"
        elif action == "delegate" and _nested(delegation, "executor_selection").get("choice_required"):
            base["next_action"] = "choose_executor"
        elif action == "clarify":
            base["next_action"] = "answer_clarification"
        else:
            base["next_action"] = "route_coding_request"
        base["chat_response"] = build_chat_response_from_delegation(delegation, thread_key=str(base["thread_key"]))
        return _finish_interaction(base, target_notice)

    plan = build_hermes_plan_payload(message, source=source, limit=limit, source_metadata=metadata)
    base["plan"] = _public_plan_payload(plan, include_message=include_message)
    contract = _nested(plan, "wrapper_contract")
    next_action = str(contract.get("next_action", "present_plan"))
    base["next_action"] = "present_plan" if next_action == "prepare_coding_delegation_after_plan_acceptance" else next_action
    base["chat_response"] = build_chat_response_from_plan(plan, thread_key=str(base["thread_key"]))
    return _finish_interaction(base, target_notice)


def build_chat_status_interaction(
    status_payload: dict[str, Any],
    *,
    source: str = "generic",
    source_metadata: dict[str, str] | None = None,
) -> dict[str, object]:
    status_metadata = _nested(status_payload, "source_metadata")
    metadata = _source_metadata("", {**{str(key): str(value) for key, value in status_metadata.items()}, **(source_metadata or {})})
    effective_source = source if source != "generic" else str(status_payload.get("source", "generic"))
    run_id = str(status_payload.get("run_id", ""))
    thread_key = _thread_key(effective_source, metadata, run_id=run_id)
    payload: dict[str, object] = {
        "schema_version": CHAT_INTERACTION_SCHEMA_VERSION,
        "source": effective_source,
        "source_metadata": metadata,
        "message_sha256": "",
        "message_length": 0,
        "thread_key": thread_key,
        "mode": "status",
        "next_action": status_payload.get("next_action", "show_status"),
        "status": status_payload,
        "status_card": build_status_card_from_status(status_payload),
        "chat_response": build_chat_response_from_status(status_payload, thread_key=thread_key),
        "redaction_policy": "metadata_only",
        "overclaim_guard": status_payload.get("overclaim_guard", _default_overclaim_guard()),
    }
    return payload


def build_chat_response_from_route(decision: dict[str, object], *, thread_key: str = "") -> dict[str, object]:
    action = str(decision.get("action", "fallback"))
    if action == "dispatch":
        selected = str(decision.get("selected_skill", "the selected workflow"))
        if selected == "cancel":
            return _chat_response(
                kind="cancellation",
                headline="I will stop this Hermes workflow.",
                body="This is a wrapper control action; it does not create a plan, handoff, or execution claim.",
                phase="cancelling",
                next_action="cancel",
                thread_key=thread_key,
                actions=[_action("cancel", "Cancel workflow", "primary"), _action("show_status", "Show status", "secondary")],
                claim_boundary="Cancellation is observed only after the wrapper records the state change.",
                extra_state={"route_action": action, "confidence": decision.get("confidence", "low"), "selected_workflow": selected},
            )
        if selected in _CLARIFICATION_SKILLS:
            return _chat_response(
                kind="clarification",
                headline="This needs a clarification workflow before planning.",
                body="I will ask one blocking question in the same thread before any plan or handoff is treated as ready.",
                phase="clarifying",
                next_action="answer_clarification",
                thread_key=thread_key,
                actions=[_action("answer:clarify", "Answer clarification", "primary"), _action("cancel", "Cancel", "secondary")],
                claim_boundary="No plan or execution has started.",
                extra_state={"route_action": action, "confidence": decision.get("confidence", "low"), "selected_workflow": selected},
            )
        policy = _selected_recommendation_policy(decision, selected)
        policy_next_action = str(policy.get("next_action", ""))
        next_action = policy_next_action if policy_next_action and policy_next_action != "show_workflow_guidance" else "dispatch_to_workflow"
        wrapper_guidance = str(policy.get("wrapper_guidance", ""))
        evidence_boundary = str(policy.get("evidence_boundary", "")) or "Routing is not execution evidence."
        body = wrapper_guidance or f"I will prepare a safe next step for `{selected}` before claiming any work happened."
        return _chat_response(
            kind="ack",
            headline="I know which workflow should handle this.",
            body=body,
            phase="routed",
            next_action=next_action,
            thread_key=thread_key,
            actions=[_action("show_status", "Show status", "secondary")],
            claim_boundary=evidence_boundary,
            extra_state={
                "route_action": action,
                "confidence": decision.get("confidence", "low"),
                "selected_workflow": selected,
                "policy_next_action": policy_next_action,
            },
        )
    if action == "clarify":
        body = str(decision.get("clarification") or "Please confirm the intended workflow before I continue.")
        return _chat_response(
            kind="clarification",
            headline="I need one clarification before routing this.",
            body=body,
            phase="clarifying",
            next_action="answer_clarification",
            thread_key=thread_key,
            actions=[_action("answer:clarify", "Answer clarification", "primary"), _action("cancel", "Cancel", "secondary")],
            claim_boundary="No execution has started.",
            extra_state={"route_action": action, "confidence": decision.get("confidence", "low")},
        )
    return _chat_response(
        kind="clarification",
        headline="I need to understand the goal before routing this.",
        body="Tell me the outcome you want, and I will choose the right workflow.",
        phase="clarifying",
        next_action="answer_clarification",
        thread_key=thread_key,
        actions=[_action("answer:clarify", "Answer clarification", "primary"), _action("cancel", "Cancel", "secondary")],
        claim_boundary="No execution has started.",
        extra_state={"route_action": action, "confidence": decision.get("confidence", "low")},
    )


def build_chat_response_from_plan(plan_payload: dict[str, object], *, thread_key: str = "") -> dict[str, object]:
    plan = _nested(plan_payload, "plan")
    contract = _nested(plan_payload, "wrapper_contract")
    if plan.get("status") == "blocked":
        return _chat_response(
            kind="clarification",
            headline="I need one answer before I can plan this.",
            body="The request is not specific enough for a safe plan yet.",
            phase="clarifying",
            next_action="ask_clarification",
            thread_key=thread_key,
            actions=[_action("answer:clarify", "Answer clarification", "primary"), _action("cancel", "Cancel", "secondary")],
            claim_boundary="No plan or execution is approved.",
        )
    actions = [_action("accept_plan", "Accept plan", "primary"), _action("revise_plan", "Revise plan", "secondary")]
    coding_delegate = _nested(contract, "coding_delegate")
    if coding_delegate.get("available"):
        actions.append(_action("prepare_handoff", "Prepare handoff", "secondary", enabled=False))
    selected = str(plan.get("recommended_workflow", "plan"))
    next_copy = (
        "Accept or revise the plan first; the handoff button stays disabled until acceptance."
        if coding_delegate.get("available")
        else "Accept or revise the plan before this moves to the selected workflow."
    )
    return _chat_response(
        kind="plan",
        headline=f"I routed this to `{selected}` because it needs a safe plan first.",
        body=f"{next_copy} A draft plan is still only planning evidence.",
        phase="planning",
        next_action="accept_or_revise_plan",
        thread_key=thread_key,
        actions=actions,
        claim_boundary="A draft plan is not execution evidence.",
        extra_state={
            "selected_workflow": selected,
            "plan_status": plan.get("status", "draft"),
            "review_gate": plan.get("review_gate", {}),
            "coding_delegate_available": bool(coding_delegate.get("available", False)),
            "evidence_not_observed": [
                "plan acceptance",
                "executor dispatch",
                "executor result",
                "verification",
            ],
        },
    )


def build_chat_response_from_delegation(delegation_payload: dict[str, object], *, thread_key: str = "") -> dict[str, object]:
    delegation = _nested(delegation_payload, "delegation")
    action = str(delegation.get("action", "fallback"))
    if action == "delegate" and delegation_payload.get("executor_handoff"):
        handoff = _nested(delegation_payload, "executor_handoff")
        executor = str(handoff.get("selected_executor_profile") or handoff.get("executor_target") or "executor")
        label = executor_label(executor)
        return _chat_response(
            kind="handoff",
            headline="A coding-agent handoff is ready.",
            body=f"I can send this to {label}, but I will not claim implementation until executor evidence is observed.",
            phase="handoff_prepared",
            next_action="send_to_executor",
            thread_key=thread_key,
            actions=[
                _action("send_to_executor", "Send to executor", "primary", payload={"selected_executor_profile": executor}),
                _action("send_to_codex", "Send to Codex", "secondary", payload={"compatibility_alias": True}),
                _action("show_status", "Show status", "secondary"),
            ],
            claim_boundary="Prepared handoff is not execution evidence.",
            extra_state={
                "delegation_action": action,
                "intent": delegation.get("intent", "unknown"),
                "work_owner_mode": delegation_payload.get("work_owner_mode", "external_executor"),
                "selected_executor_profile": delegation_payload.get("selected_executor_profile", "codex"),
                "dispatch_policy": delegation_payload.get("dispatch_policy", "ask_before_dispatch"),
                "executor_target": handoff.get("executor_target", "codex"),
            },
        )
    if action == "delegate" and delegation_payload.get("prompt_handoff"):
        prompt_handoff = _nested(delegation_payload, "prompt_handoff")
        selected = str(prompt_handoff.get("selected_executor_profile") or "executor")
        return _chat_response(
            kind="handoff",
            headline="A prompt handoff is ready.",
            body=f"I prepared a copyable {selected} prompt. This is not dispatch, execution, review, CI, or merge evidence.",
            phase="prompt_handoff_prepared",
            next_action="show_prompt_handoff",
            thread_key=thread_key,
            actions=[
                _action("show_prompt_handoff", "Show prompt", "primary", payload={"selected_executor_profile": selected}),
                _action("copy_prompt_handoff", "Copy prompt", "secondary", payload={"selected_executor_profile": selected}),
                _action("choose_executor", "Change executor", "secondary"),
                _action("show_status", "Show status", "secondary"),
            ],
            claim_boundary="Prompt handoff is prepared only; OMH has not dispatched it to an executor.",
            extra_state={
                "delegation_action": action,
                "intent": delegation.get("intent", "unknown"),
                "work_owner_mode": "prompt_only_handoff",
                "selected_executor_profile": selected,
                "dispatch_policy": "prepare_only",
                "dispatchable": False,
            },
        )
    if action == "delegate" and _nested(delegation_payload, "executor_selection").get("choice_required"):
        return _chat_response(
            kind="handoff",
            headline="Choose who should own the coding work.",
            body="I can keep this with Hermes, prepare a prompt for another coding agent, or prepare a Codex lifecycle handoff.",
            phase="executor_choice_required",
            next_action="choose_executor",
            thread_key=thread_key,
            actions=[_action("choose_executor", "Choose executor", "primary"), _action("show_status", "Show status", "secondary")],
            claim_boundary="Executor choice is not dispatch or implementation evidence.",
            extra_state={
                "delegation_action": action,
                "intent": delegation.get("intent", "unknown"),
                "work_owner_mode": "external_executor",
                "selected_executor_profile": None,
                "dispatchable": False,
                "executor_options": _nested(delegation_payload, "executor_selection").get("options", []),
            },
        )
    if action == "clarify":
        workflow = str(delegation.get("recommended_workflow", ""))
        if workflow in _RETAINED_DELEGATION_SKILLS:
            return _chat_response(
                kind="clarification",
                headline="I need one clarification before starting this Hermes workflow.",
                body="This stays with Hermes; I will clarify scope and evidence boundaries before preparing the retained brief.",
                phase="clarifying",
                next_action="answer_clarification",
                thread_key=thread_key,
                actions=[_action("answer:clarify", "Answer clarification", "primary"), _action("cancel", "Cancel", "secondary")],
                claim_boundary="Retained Hermes guidance is not observed work.",
                extra_state={
                    "delegation_action": action,
                    "intent": delegation.get("intent", "unknown"),
                    "recommended_workflow": workflow,
                },
            )
        return _chat_response(
            kind="clarification",
            headline="I need one clarification before sending this to an executor.",
            body="The request looks like coding work, but the handoff is not specific enough yet.",
            phase="clarifying",
            next_action="answer_clarification",
            thread_key=thread_key,
            actions=[_action("answer:clarify", "Answer clarification", "primary"), _action("cancel", "Cancel", "secondary")],
            claim_boundary="No executor handoff is dispatchable.",
            extra_state={"delegation_action": action, "intent": delegation.get("intent", "unknown")},
        )
    return _chat_response(
        kind="clarification",
        headline="I need to route this before coding delegation.",
        body="I will ask for the missing outcome before preparing an executor handoff.",
        phase="clarifying",
        next_action="route_coding_request",
        thread_key=thread_key,
        actions=[_action("answer:clarify", "Answer clarification", "primary"), _action("cancel", "Cancel", "secondary")],
        claim_boundary="No executor handoff is dispatchable.",
        extra_state={"delegation_action": action, "intent": delegation.get("intent", "unknown")},
    )


def build_chat_response_from_status(status_payload: dict[str, Any], *, thread_key: str = "") -> dict[str, object]:
    next_action = str(status_payload.get("next_action", "show_status"))
    kind, headline, body, claim_boundary = _STATUS_COPY.get(
        next_action,
        ("status", "I have a conservative status update.", str(status_payload.get("safe_summary", "")), "Only observed evidence can support completion claims."),
    )
    actions = [_action("show_status", "Show status", "secondary")]
    if next_action == "dispatch_to_executor":
        actions.insert(0, _action("send_to_executor", "Send to executor", "primary"))
        if str(_nested(status_payload, "prepared").get("executor_target", "")) == "codex":
            actions.insert(1, _action("send_to_codex", "Send to Codex", "secondary", payload={"compatibility_alias": True}))
    return _chat_response(
        kind=kind,
        headline=headline,
        body=body,
        phase=_phase_for_next_action(next_action),
        next_action=next_action,
        thread_key=thread_key,
        actions=actions,
        claim_boundary=claim_boundary,
        extra_state={
            "execution_observed": _nested(status_payload, "execution").get("observed", False),
            "verification_observed": _nested(status_payload, "verification").get("observed", False),
            "review_required": _nested(status_payload, "review").get("required", False),
            "review_status": _nested(status_payload, "review").get("status", "not_observed"),
            "ci_status": _nested(status_payload, "ci").get("status", "not_observed"),
            "merge_readiness_status": _nested(status_payload, "merge_readiness").get("status", "not_observed"),
            "merge_status": _nested(status_payload, "merge").get("status", "not_observed"),
        },
        status_card=build_status_card_from_status(status_payload),
    )


def build_status_card_from_status(status_payload: dict[str, Any]) -> dict[str, object]:
    next_action = str(status_payload.get("next_action", "show_status"))
    kind, headline, body, claim_boundary = _STATUS_COPY.get(
        next_action,
        ("status", "I have a conservative status update.", str(status_payload.get("safe_summary", "")), "Only observed evidence can support completion claims."),
    )
    card: dict[str, object] = {
        "schema_version": STATUS_CARD_SCHEMA_VERSION,
        "run_id": str(status_payload.get("run_id", "")),
        "kind": kind,
        "severity": _status_card_severity(next_action),
        "headline": headline,
        "summary": body,
        "next_action": next_action,
        "primary_action": "send_to_executor" if next_action == "dispatch_to_executor" else "show_status",
        "steps": _status_card_steps(status_payload, next_action),
        "claim_boundary": claim_boundary,
    }
    harness_progress = status_payload.get("harness_progress")
    if isinstance(harness_progress, dict) and harness_progress:
        card["harness_progress"] = harness_progress
    return card


def _base_interaction(
    message: str,
    *,
    source: str,
    source_metadata: dict[str, str],
    mode: str,
    include_message: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": CHAT_INTERACTION_SCHEMA_VERSION,
        "source": source,
        "source_metadata": source_metadata,
        "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest(),
        "message_length": len(message),
        "thread_key": _thread_key(source, source_metadata, message=message),
        "mode": mode,
        "next_action": "unknown",
        "redaction_policy": "stdout_includes_message" if include_message else "metadata_only",
        "overclaim_guard": _default_overclaim_guard(),
    }
    if include_message:
        payload["message"] = message
    return payload


def _finish_interaction(payload: dict[str, object], target_notice: dict[str, object] | None) -> dict[str, object]:
    if not target_notice:
        return payload
    payload["target_notice"] = target_notice
    topology = target_notice.get("topology")
    if isinstance(topology, dict):
        payload["target_topology"] = topology
    response = payload.get("chat_response")
    if isinstance(response, dict):
        payload["chat_response"] = _chat_response_with_target_notice(response, target_notice)
    return payload


def _chat_response_with_target_notice(response: dict[str, object], target_notice: dict[str, object]) -> dict[str, object]:
    updated = dict(response)
    state = dict(_nested(updated, "state"))
    topology = target_notice.get("topology")
    if isinstance(topology, dict):
        state["target_topology"] = topology
    state["target_notice"] = {
        "action": target_notice.get("action", ""),
        "persistence": target_notice.get("persistence", ""),
        "transition": topology.get("transition", "") if isinstance(topology, dict) else "",
    }
    updated["state"] = state
    body = str(updated.get("body", ""))
    notice_body = str(target_notice.get("body", ""))
    if notice_body and notice_body not in body:
        updated["body"] = f"{body} {notice_body}".strip()
    actions = list(updated.get("actions", []))
    action_ids = {str(action.get("id", "")) for action in actions if isinstance(action, dict)}
    if "show_target_status" not in action_ids:
        actions.append(_action("show_target_status", "Show target status", "secondary"))
    if target_notice.get("action") == "ask_to_apply_target_change" and "apply_target_change" not in action_ids:
        action_payload: dict[str, object] = {"target_id": str(target_notice.get("target_id", ""))}
        apply_payload = target_notice.get("apply_payload")
        if isinstance(apply_payload, dict):
            action_payload["target_observation"] = apply_payload
        actions.append(
            _action(
                "apply_target_change",
                "Apply target setup",
                "secondary",
                payload=action_payload,
            )
        )
    updated["actions"] = actions
    updated["claim_boundary"] = f"{updated.get('claim_boundary', '')} {target_notice.get('claim_boundary', '')}".strip()
    return updated


def _resolve_mode(mode: str, route: dict[str, object]) -> str:
    if mode != "auto":
        return mode
    action = str(route.get("action", "fallback"))
    if action != "dispatch":
        return _ROUTE_TO_MODE.get(action, "clarify")
    selected = str(route.get("selected_skill", ""))
    if selected == "cancel":
        return "route"
    if selected in _CLARIFICATION_SKILLS:
        return "clarify"
    if selected in _DIRECT_WORKFLOW_SKILLS:
        return "route"
    return _ROUTE_TO_MODE.get(action, "plan")


def _selected_recommendation_policy(decision: dict[str, object], selected: str) -> dict[str, object]:
    recommendations = decision.get("recommendations", [])
    if not isinstance(recommendations, list):
        return {}
    for item in recommendations:
        if isinstance(item, dict) and str(item.get("skill", "")) == selected:
            return {
                "next_action": item.get("next_action", ""),
                "evidence_boundary": item.get("evidence_boundary", ""),
                "wrapper_guidance": item.get("wrapper_guidance", ""),
            }
    return {}


def _public_plan_payload(plan_payload: dict[str, object], *, include_message: bool) -> dict[str, object]:
    payload = dict(plan_payload)
    plan = dict(_nested(payload, "plan"))
    if not include_message and plan.get("task_statement"):
        plan["task_statement"] = "{message}"
    payload["plan"] = plan
    if not include_message:
        payload.pop("message", None)
    return payload


def _source_metadata(event_or_message: dict[str, Any] | str, explicit: dict[str, str] | None) -> dict[str, str]:
    metadata: dict[str, str] = {}
    if isinstance(event_or_message, dict):
        metadata.update(extract_source_metadata(event_or_message))
    metadata.update({str(key): str(value) for key, value in (explicit or {}).items() if str(value)})
    return compact_source_metadata(metadata)


def _thread_key(source: str, metadata: dict[str, str], *, message: str = "", run_id: str = "") -> str:
    channel = metadata.get("channel_ref") or "channel"
    event = metadata.get("source_event_id") or run_id
    if not event:
        event = hashlib.sha256(message.encode("utf-8")).hexdigest()[:12]
    target_scope = _target_scope_key(metadata)
    if target_scope:
        return f"{source}:{channel}:{target_scope}:{event}"
    return f"{source}:{channel}:{event}"


def _target_scope_key(metadata: dict[str, str]) -> str:
    parts = [
        metadata.get("hermes_home", ""),
        metadata.get("agent_ref", ""),
        metadata.get("target_ref", ""),
        metadata.get("runtime_ref", ""),
    ]
    if not any(parts):
        return ""
    basis = "|".join(parts)
    return f"target-{hashlib.sha256(basis.encode('utf-8')).hexdigest()[:12]}"


def _chat_response(
    *,
    kind: str,
    headline: str,
    body: str,
    phase: str,
    next_action: str,
    thread_key: str,
    actions: list[dict[str, object]],
    claim_boundary: str,
    extra_state: dict[str, object] | None = None,
    status_card: dict[str, object] | None = None,
) -> dict[str, object]:
    state: dict[str, object] = {"phase": phase, "next_action": next_action}
    if thread_key:
        state["thread_key"] = thread_key
    state.update(extra_state or {})
    response: dict[str, object] = {
        "schema_version": CHAT_RESPONSE_SCHEMA_VERSION,
        "kind": kind,
        "visibility": "thread",
        "headline": headline,
        "body": body,
        "state": state,
        "actions": actions,
        "claim_boundary": claim_boundary,
    }
    if status_card:
        response["status_card"] = status_card
    return response


def _action(action_id: str, label: str, style: str, *, enabled: bool = True, payload: dict[str, object] | None = None) -> dict[str, object]:
    if action_id not in VISIBLE_ACTIONS and not action_id.startswith("answer:"):
        raise ValueError(f"unsupported chat response action: {action_id}")
    return {"id": action_id, "label": label, "style": style, "enabled": enabled, "payload": payload or {}}


def _phase_for_next_action(next_action: str) -> str:
    return {
        "prepare_coding_delegation": "preparing",
        "dispatch_to_executor": "handoff_prepared",
        "wait_for_executor_evidence": "dispatched",
        "surface_executor_blocker": "blocked",
        "surface_review_blocker": "blocked",
        "surface_ci_blocker": "blocked",
        "surface_merge_blocker": "blocked",
        "record_review_evidence": "awaiting_review",
        "record_ci_evidence": "awaiting_ci",
        "record_merge_readiness": "awaiting_merge_readiness",
        "record_verification_evidence": "awaiting_verification",
        "report_completion_with_evidence": "reportable",
        "report_merge_ready": "merge_ready",
        "report_merged": "merged",
    }.get(next_action, "status")


def _status_card_severity(next_action: str) -> str:
    if next_action.startswith("surface_"):
        return "blocked"
    if next_action in {"report_merge_ready", "report_merged", "report_completion_with_evidence"}:
        return "success"
    if next_action in {"dispatch_to_executor", "record_review_evidence", "record_ci_evidence", "record_merge_readiness"}:
        return "attention"
    return "neutral"


def _status_card_steps(status_payload: dict[str, Any], next_action: str) -> list[dict[str, object]]:
    review = _nested(status_payload, "review")
    ci = _nested(status_payload, "ci")
    merge = _nested(status_payload, "merge")
    merge_readiness = _nested(status_payload, "merge_readiness")
    steps = [
        _status_card_step("handoff", "Handoff", _handoff_step_state(status_payload, next_action), "Prepared executor handoff."),
        _status_card_step("execution", "Execution", _observed_step_state(_nested(status_payload, "execution")), "Observed executor result."),
        _status_card_step("verification", "Verification", _verification_step_state(_nested(status_payload, "verification")), "Observed verification evidence."),
        _status_card_step("review", "Review", _gate_step_state(review, required=bool(review.get("required", False))), "Review evidence when required."),
        _status_card_step("ci", "CI", _gate_step_state(ci, required=bool(ci) or str(review.get("status", "")) == "passed"), "CI evidence before merge readiness."),
        _status_card_step(
            "merge_ready",
            "Merge Ready",
            _merge_ready_step_state(merge_readiness, next_action),
            "Explicit merge-readiness evidence.",
        ),
        _status_card_step("merged", "Merged", _merged_step_state(merge), "Observed merge evidence."),
    ]
    return steps


def _status_card_step(step_id: str, label: str, state: str, detail: str) -> dict[str, object]:
    return {"id": step_id, "label": label, "state": state, "detail": detail}


def _handoff_step_state(status_payload: dict[str, Any], next_action: str) -> str:
    if next_action in {"prepare_coding_delegation", "clarify_coding_request", "route_coding_request"}:
        return "pending"
    if next_action == "dispatch_to_executor":
        return "ready"
    if _nested(status_payload, "prepared").get("handoff_available", False):
        return "complete"
    return "pending"


def _observed_step_state(value: dict[str, Any]) -> str:
    status = str(value.get("status", "not_observed"))
    if status in {"blocked", "failed"}:
        return "blocked"
    if bool(value.get("observed", False)) and status == "completed":
        return "complete"
    return "pending"


def _verification_step_state(value: dict[str, Any]) -> str:
    status = str(value.get("status", ""))
    if status in {"blocked", "failed"}:
        return "blocked"
    return "complete" if bool(value.get("observed", False)) else "pending"


def _gate_step_state(value: dict[str, Any], *, required: bool) -> str:
    status = str(value.get("status", "not_observed"))
    if not required and status in {"not_required", "not_observed"}:
        return "not_required"
    if status == "passed":
        return "complete"
    if status in {"failed", "blocked"}:
        return "blocked"
    return "pending"


def _merge_ready_step_state(value: dict[str, Any], next_action: str) -> str:
    status = str(value.get("status", "not_observed"))
    if next_action == "report_merge_ready" or status == "ready":
        return "complete"
    if status in {"blocked", "failed"}:
        return "blocked"
    return "pending"


def _merged_step_state(value: dict[str, Any]) -> str:
    status = str(value.get("status", "not_observed"))
    if status == "merged":
        return "complete"
    if status == "blocked":
        return "blocked"
    return "pending"


def _default_overclaim_guard() -> list[str]:
    return [
        "Prepared handoff is not execution evidence.",
        "Review, verification, CI, and merge status require separate observed evidence.",
        "Hermes orchestrates; selected coding executors perform main coding work.",
    ]


def _nested(payload: dict[str, Any], key: str) -> dict[str, Any]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}
