from __future__ import annotations

import hashlib
from typing import Any

from ..ingress import CHAT_SOURCES, compact_source_metadata, extract_message_text, extract_source_metadata
from ..routing.chat import public_route_payload, route_chat_message
from ..coding_delegation import build_coding_delegation_payload
from ..executors import executor_label
from ..goal_loop import build_loop_start_card
from ..hermes_planning import build_hermes_plan_payload
from ..skills.catalog import installable_skill_definitions, primary_harness_for_skill, retained_delegation_skill_names
from .hermes_runtime import (
    hermes_coding_team_body,
    hermes_coding_team_claim_boundary,
    hermes_coding_team_extra_action_specs,
)


CHAT_INTERACTION_SCHEMA_VERSION = "chat_interaction/v1"
CHAT_RESPONSE_SCHEMA_VERSION = "chat_response/v1"
STATUS_CARD_SCHEMA_VERSION = "status_card/v1"
SKILL_PICKER_SCHEMA_VERSION = "omh_skill_picker/v1"
COMMAND_PREVIEW_SCHEMA_VERSION = "omh_command_preview/v1"
INTERACTION_MODES = ("auto", "route", "plan", "delegate")
VISIBLE_ACTIONS = (
    "answer:clarify",
    "show_command_preview",
    "show_skill_picker",
    "choose_skill",
    "search_skills",
    "accept_plan",
    "revise_plan",
    "prepare_handoff",
    "choose_executor",
    "show_prompt_handoff",
    "copy_prompt_handoff",
    "show_runtime_handoff",
    "show_coding_team_path",
    "start_runtime",
    "start_hermes_coding",
    "start_team",
    "start_swarm",
    "prepare_worktree",
    "record_runtime_observation",
    "send_to_executor",
    "send_to_codex",
    "open_executor_session",
    "attach_executor_session",
    "refresh_executor_status",
    "record_executor_completed",
    "record_executor_blocked",
    "record_executor_failed",
    "ask_hermes_verify",
    "show_status",
    "show_target_status",
    "apply_target_change",
    "choose_permission_profile",
    "assess_loopability",
    "convert_to_loop_goal",
    "route_direct_task",
    "start_ultraprocess",
    "start_loop",
    "run_loop_tick",
    "show_loop_status",
    "show_loop_queue",
    "prepare_loop_handoff",
    "observe_loop_queue",
    "block_loop_queue",
    "keep_memory",
    "forget_memory",
    "update_memory",
    "change_memory_scope",
    "apply_memory_updates",
    "show_memory_status",
    "cancel",
)
_ROUTE_TO_MODE = {"dispatch": "plan", "clarify": "clarify", "fallback": "clarify"}
_CLARIFICATION_SKILLS = {"deep-interview"}
_ROUTER_SKILL = "oh-my-hermes"
_SKILL_PICKER_TOKENS = frozenset({"omh", "ohmy", "skills"})
_SKILL_PICKER_HELP_TOKENS = frozenset({"", "help", "menu", "list", "commands", "workflows", "skills"})
_COMMAND_PREVIEW_PREFIXES = ("./", "/")
_COMMAND_PREVIEW_ALIAS = "omh"
_SKILL_PICKER_ENTRIES = (
    ("oh-my-hermes", "Route for me", "Let Hermes choose the safest workflow.", "./omh <request>"),
    ("deep-interview", "Deep Interview", "Clarify fuzzy goals before planning.", "./deep-interview <request>"),
    ("ralplan", "Ralplan", "Research and plan before execution.", "./ralplan <request>"),
    ("loop", "Loop", "Iterate on a loopable long-horizon goal.", "./loop <goal>"),
    ("ultraprocess", "Ultra Process", "Run one research-plan-implement-review-sync cycle.", "./ultraprocess <request>"),
    ("feedback-triage", "Feedback Triage", "Turn customer or product signals into investigation.", "./feedback-triage <signal>"),
    ("web-research", "Web Research", "Gather source-backed current evidence.", "./web-research <question>"),
    ("code-review", "Code Review", "Review completed work without overclaiming evidence.", "./code-review <scope>"),
    ("materials-package", "Materials Package", "Shape PPT, PDF, spreadsheet, document, or Markdown deliverables.", "./materials-package <brief>"),
    ("automation-blueprint", "Automation Blueprint", "Prepare recurring Hermes scheduled-ops workflows.", "./automation-blueprint <intent>"),
    ("doctor", "Doctor", "Check OMH install and Hermes registration health.", "./doctor"),
)
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
        "I have prepared the handoff, but executor/runtime dispatch is not observed yet.",
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
    resolved_mode = _resolve_mode(mode, route, message=message)
    base = _base_interaction(message, source=source, source_metadata=metadata, mode=resolved_mode, include_message=include_message)
    base["route"] = public_route_payload(route, include_message=include_message)

    if resolved_mode == "route" and _is_command_preview_invocation(message):
        base["chat_response"] = build_chat_response_from_route(
            route,
            thread_key=str(base["thread_key"]),
            message=message,
            include_message=include_message,
        )
        base["next_action"] = str(_nested(base["chat_response"], "state").get("next_action", "show_command_preview"))
        return _finish_interaction(base, target_notice)

    if resolved_mode == "clarify" or route["action"] != "dispatch":
        base["next_action"] = "answer_clarification"
        base["chat_response"] = build_chat_response_from_route(
            route,
            thread_key=str(base["thread_key"]),
            message=message,
            include_message=include_message,
        )
        return _finish_interaction(base, target_notice)

    if resolved_mode == "route":
        base["chat_response"] = build_chat_response_from_route(
            route,
            thread_key=str(base["thread_key"]),
            message=message,
            include_message=include_message,
        )
        base["next_action"] = str(_nested(base["chat_response"], "state").get("next_action", "dispatch_to_workflow"))
        loop_start_card = _nested(_nested(base["chat_response"], "state"), "loop_start_card")
        if loop_start_card:
            base["loop_start_card"] = loop_start_card
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
        elif action == "delegate" and delegation.get("runtime_handoff"):
            base["next_action"] = "show_runtime_handoff"
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


def build_chat_response_from_route(
    decision: dict[str, object],
    *,
    thread_key: str = "",
    message: str = "",
    include_message: bool = False,
) -> dict[str, object]:
    action = str(decision.get("action", "fallback"))
    if _is_command_preview_invocation(message):
        return _command_preview_response(decision, thread_key=thread_key, message=message)
    if action == "dispatch":
        selected = str(decision.get("selected_skill", "the selected workflow"))
        if selected == _ROUTER_SKILL and _is_skill_picker_invocation(message):
            return _skill_picker_response(decision, thread_key=thread_key, message=message)
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
        if selected == "loop" or policy_next_action == "start_goal_loop":
            evidence_boundary = str(policy.get("evidence_boundary", "")) or "A goal loop is orchestration state only."
            body = str(policy.get("wrapper_guidance", "")) or (
                "Start the loop interview, choose a permission profile, and keep every later step inside the recorded authority envelope."
            )
            loop_start_card = build_loop_start_card(
                message or selected,
                include_goal=include_message,
                source=str(decision.get("source", "generic")),
            )
            assessment = loop_start_card.get("loopability_assessment", {})
            loop_next_action = str(assessment.get("recommended_next_action", "start_goal_loop"))
            loopability = str(assessment.get("loopability", "loopable"))
            if loopability == "direct_task":
                headline = "This looks like a direct task, not a loop."
                body = "I can route it to a one-cycle delivery workflow unless you explicitly want repeated discovery."
                primary_action = "route_direct_task"
            elif loopability in {"needs_reframe", "north_star_only"}:
                headline = "This is a north star; I will shape the first loop goal."
                body = "I will keep the ambition, then ask for or propose a bounded arena, observable problem, and next verification before cycling."
                primary_action = "convert_to_loop_goal"
            elif loopability == "external_wait_only":
                headline = "This depends on external evidence."
                body = "I can record the external wait or help choose a local proxy loop goal before continuing."
                primary_action = "assess_loopability"
            else:
                headline = "I can start a goal loop for this."
                primary_action = "choose_permission_profile"
            loop_actions = [_action(primary_action, primary_action.replace("_", " "), "primary")]
            if primary_action != "choose_permission_profile":
                loop_actions.append(
                    _action("choose_permission_profile", "Choose permission profile", "secondary", enabled=loopability == "loopable")
                )
            loop_actions.extend(
                [
                    _action("start_loop", "Start loop", "primary", enabled=loopability == "loopable"),
                    _action("run_loop_tick", "Run loop tick", "secondary", enabled=False),
                    _action("show_loop_queue", "Show loop queue", "secondary", enabled=False),
                    _action("show_loop_status", "Show loop status", "secondary"),
                    _action("cancel", "Cancel", "secondary"),
                ]
            )
            return _chat_response(
                kind="loop",
                headline=headline,
                body=body,
                phase="loop_setup",
                next_action=loop_next_action if loop_next_action else "start_goal_loop",
                thread_key=thread_key,
                actions=loop_actions,
                claim_boundary=evidence_boundary,
                extra_state={
                    "route_action": action,
                    "confidence": decision.get("confidence", "low"),
                    "selected_workflow": selected,
                    "policy_next_action": policy_next_action,
                    "loopability_assessment": assessment,
                    "permission_profile_required": True,
                    "loop_start_card": loop_start_card,
                    "evidence_not_observed": [
                        "executor/runtime dispatch",
                        "implementation",
                        "review",
                        "CI",
                        "merge",
                        "external publication",
                        "market response",
                        "goal completion",
                        "worktree creation",
                        "subagent dispatch",
                        "connector I/O",
                    ],
                    "runtime_tick_contract": "After start, wrappers may call the loop tick backend with deterministic queue shape to prepare the next queued worktree/subagent/connector step without claiming observation.",
                },
            )
        if selected == "ultraprocess" or policy_next_action == "start_ultraprocess":
            evidence_boundary = str(policy.get("evidence_boundary", "")) or "A delivery process route is not execution evidence."
            body = str(policy.get("wrapper_guidance", "")) or (
                "I will shape this into one planning, implementation handoff, review, docs sync, and PR-ready cycle."
            )
            return _chat_response(
                kind="process",
                headline="I can run one delivery process cycle for this.",
                body=body,
                phase="process_setup",
                next_action="start_ultraprocess",
                thread_key=thread_key,
                actions=[
                    _action("start_ultraprocess", "Start process", "primary"),
                    _action("prepare_handoff", "Prepare handoff", "secondary", enabled=False),
                    _action("show_status", "Show status", "secondary"),
                    _action("cancel", "Cancel", "secondary"),
                ],
                claim_boundary=evidence_boundary,
                extra_state={
                    "route_action": action,
                    "confidence": decision.get("confidence", "low"),
                    "selected_workflow": selected,
                    "policy_next_action": policy_next_action,
                    "cycle_policy": "single_cycle",
                    "continues_after_feedback": False,
                    "process_stages": [
                        "codebase_or_source_research",
                        "ralplan",
                        "implementation_handoff",
                        "code_review",
                        "docs_sync_when_needed",
                        "pr_ready_or_pr_observed_report",
                        "stop_or_recommend_next_workflow",
                    ],
                    "evidence_not_observed": [
                        "accepted plan",
                        "executor/runtime dispatch",
                        "implementation",
                        "code review",
                        "docs sync",
                        "CI",
                        "PR creation",
                        "merge readiness",
                        "merge",
                    ],
                },
            )
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
                "executor/runtime dispatch",
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
    if action == "delegate" and delegation_payload.get("runtime_handoff"):
        runtime_handoff = _nested(delegation_payload, "runtime_handoff")
        selected = str(runtime_handoff.get("selected_executor_profile") or "runtime")
        runtime_profile = _nested(runtime_handoff, "runtime_profile")
        runtime_label = str(runtime_profile.get("label") or executor_label(selected))
        primary_action = "start_hermes_coding" if selected == "hermes" else "start_runtime"
        primary_label = "Start Hermes coding" if selected == "hermes" else "Start runtime"
        extra_actions = (
            [_action_from_spec(spec) for spec in hermes_coding_team_extra_action_specs(selected_executor_profile=selected)]
            if selected == "hermes"
            else []
        )
        body = (
            hermes_coding_team_body()
            if selected == "hermes"
            else (
                f"I prepared a {runtime_label} runtime contract with team/swarm, worker-protocol, and worktree guidance. "
                "This is not runtime start, implementation, review, CI, or merge evidence."
            )
        )
        return _chat_response(
            kind="handoff",
            headline="A runtime handoff is ready.",
            body=body,
            phase="runtime_handoff_prepared",
            next_action="show_runtime_handoff",
            thread_key=thread_key,
            actions=[
                _action("show_runtime_handoff", "Show runtime", "primary", payload={"selected_executor_profile": selected}),
                *extra_actions,
                _action(primary_action, primary_label, "primary", enabled=False, payload={"selected_executor_profile": selected}),
                _action("prepare_worktree", "Prepare worktree", "secondary", enabled=False, payload={"selected_executor_profile": selected}),
                _action("start_team", "Start team", "secondary", enabled=False, payload={"selected_executor_profile": selected}),
                _action("start_swarm", "Start swarm", "secondary", enabled=False, payload={"selected_executor_profile": selected}),
                _action("choose_executor", "Change runtime", "secondary"),
                _action("show_status", "Show status", "secondary"),
            ],
            claim_boundary=(
                hermes_coding_team_claim_boundary()
                if selected == "hermes"
                else "Runtime handoff is prepared only; OMH has not started Hermes, OMX, OMO, OMC, workers, tmux, or worktrees."
            ),
            extra_state={
                "delegation_action": action,
                "intent": delegation.get("intent", "unknown"),
                "work_owner_mode": "runtime_handoff",
                "selected_executor_profile": selected,
                "runtime_family": runtime_profile.get("runtime_family", ""),
                "underlying_agent": runtime_profile.get("underlying_agent", ""),
                "dispatch_policy": "prepare_only",
                "dispatchable": False,
            },
        )
    if action == "delegate" and _nested(delegation_payload, "executor_selection").get("choice_required"):
        return _chat_response(
            kind="handoff",
            headline="Choose who should own the coding work.",
            body="I can keep this with Hermes, prepare an oh-my runtime handoff, prepare a prompt for another coding agent, or prepare a Codex lifecycle handoff.",
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


def _resolve_mode(mode: str, route: dict[str, object], *, message: str = "") -> str:
    if mode != "auto":
        return mode
    if _is_command_preview_invocation(message):
        return "route"
    action = str(route.get("action", "fallback"))
    if action != "dispatch":
        return _ROUTE_TO_MODE.get(action, "clarify")
    selected = str(route.get("selected_skill", ""))
    if selected == "cancel":
        return "route"
    if selected == _ROUTER_SKILL and _is_skill_picker_invocation(message):
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


def _is_skill_picker_invocation(message: str) -> bool:
    parts = message.strip().split(maxsplit=1)
    if not parts:
        return False
    first = parts[0].strip(":,").lower()
    for prefix in ("./", "/", "$", "@"):
        if first.startswith(prefix):
            first = first[len(prefix) :].strip(":,")
            break
    if first not in _SKILL_PICKER_TOKENS:
        return False
    rest = parts[1].strip().lower() if len(parts) > 1 else ""
    return rest in _SKILL_PICKER_HELP_TOKENS


def _is_command_preview_invocation(message: str) -> bool:
    token = _first_token(message).lower()
    if not token:
        return False
    if len(message.strip().split(maxsplit=1)) > 1:
        return False
    for prefix in _COMMAND_PREVIEW_PREFIXES:
        if not token.startswith(prefix):
            continue
        typed = token[len(prefix) :].strip(":,")
        return typed != _COMMAND_PREVIEW_ALIAS and _COMMAND_PREVIEW_ALIAS.startswith(typed)
    return False


def _command_preview_response(decision: dict[str, object], *, thread_key: str = "", message: str = "") -> dict[str, object]:
    preview = _command_preview_state(message, source=str(decision.get("source", "generic")))
    return _chat_response(
        kind="command_preview",
        headline="Open OMH.",
        body="Complete or choose `omh` to open the OMH workflow picker. The preview shows one top-level entry instead of every installed workflow.",
        phase="command_preview",
        next_action="show_command_preview",
        thread_key=thread_key,
        actions=[
            _action(
                "show_command_preview",
                "Show omh",
                "primary",
                payload={
                    "schema_version": COMMAND_PREVIEW_SCHEMA_VERSION,
                    "suggestions": preview["suggestions"],
                },
            ),
            _action(
                "show_skill_picker",
                "Open picker",
                "secondary",
                payload={
                    "insert_text": preview["suggestions"][0]["insert_text"] if preview["suggestions"] else "./omh",
                    "opens_schema": SKILL_PICKER_SCHEMA_VERSION,
                },
            ),
        ],
        claim_boundary="Command preview is autocomplete guidance only; it is not routing, plan acceptance, dispatch, execution, review, CI, or verification evidence.",
        extra_state={
            "route_action": decision.get("action", "fallback"),
            "confidence": decision.get("confidence", "low"),
            "selected_workflow": _ROUTER_SKILL,
            "command_preview": preview,
        },
    )


def _command_preview_state(message: str, *, source: str) -> dict[str, object]:
    token = _first_token(message)
    prefix = _command_preview_prefix(token)
    insert_text = f"{prefix}{_COMMAND_PREVIEW_ALIAS}" if prefix else "./omh"
    return {
        "schema_version": COMMAND_PREVIEW_SCHEMA_VERSION,
        "trigger": token,
        "source": source,
        "selection_mode": "single_top_level_command",
        "suggestions": [
            {
                "id": _COMMAND_PREVIEW_ALIAS,
                "label": _COMMAND_PREVIEW_ALIAS,
                "insert_text": insert_text,
                "description": "Open the OMH workflow picker.",
                "opens_schema": SKILL_PICKER_SCHEMA_VERSION,
                "action_id": "show_skill_picker",
            }
        ],
        "top_level_aliases_only": True,
        "hide_installed_workflows_until_picker_opens": True,
        "rendering_hints": {
            "discord": "When the user types `./`, show only `omh`; selecting it inserts `./omh` and opens the picker.",
            "slack": "When the user types `/`, show only `omh`; selecting it inserts `/omh` and opens the picker.",
            "telegram": "When the user sends `/` or `/om`, show the `omh` bot command or an Open omh inline button.",
            "hermes_tui": "Render one preview row: `omh` opens the OMH workflow picker.",
        },
        "claim_boundary": "This preview records no workflow selection; it only helps the wrapper render autocomplete.",
    }


def _command_preview_prefix(token: str) -> str:
    for prefix in _COMMAND_PREVIEW_PREFIXES:
        if token.lower().startswith(prefix):
            return prefix
    return ""


def _skill_picker_response(decision: dict[str, object], *, thread_key: str = "", message: str = "") -> dict[str, object]:
    picker = _skill_picker_state(message, source=str(decision.get("source", "generic")))
    return _chat_response(
        kind="skill_picker",
        headline="Choose an OMH workflow.",
        body="Pick a workflow, or choose Route for me and Hermes will select the safest next step from the request.",
        phase="skill_selection",
        next_action="choose_skill",
        thread_key=thread_key,
        actions=[
            _action(
                "choose_skill",
                "Choose workflow",
                "primary",
                payload={
                    "schema_version": SKILL_PICKER_SCHEMA_VERSION,
                    "selection_mode": "single_select",
                    "options": picker["options"],
                },
            ),
            _action("search_skills", "Search workflows", "secondary", payload={"input_schema": {"query": "string"}}),
            _action("show_status", "Show status", "secondary"),
        ],
        claim_boundary="Choosing a skill is routing intent only; it is not plan acceptance, dispatch, execution, review, CI, or verification evidence.",
        extra_state={
            "route_action": decision.get("action", "dispatch"),
            "confidence": decision.get("confidence", "low"),
            "selected_workflow": _ROUTER_SKILL,
            "skill_picker": picker,
            "direct_invocation_aliases": ["./omh", "/omh", "./skills", "/skills"],
        },
    )


def _skill_picker_state(message: str, *, source: str) -> dict[str, object]:
    installed = {definition.name: definition for definition in installable_skill_definitions()}
    options = []
    for skill_id, label, description, direct_invocation in _SKILL_PICKER_ENTRIES:
        definition = installed.get(skill_id)
        if definition is None:
            continue
        options.append(
            {
                "id": skill_id,
                "label": label,
                "description": description,
                "direct_invocation": direct_invocation,
                "harness": primary_harness_for_skill(skill_id),
                "action_id": "choose_skill",
                "payload": {
                    "skill": skill_id,
                    "direct_invocation": direct_invocation,
                    "preserve_original_message": True,
                },
            }
        )
    return {
        "schema_version": SKILL_PICKER_SCHEMA_VERSION,
        "trigger": _first_token(message),
        "source": source,
        "selection_mode": "single_select",
        "options": options,
        "rendering_hints": {
            "discord": "Render options as a select menu or compact buttons in the current thread.",
            "slack": "Render options as a static select or button list in the current thread.",
            "hermes_tui": "Render options as a compact command list; keep real skill names unchanged.",
        },
        "claim_boundary": "This picker records routing intent only; selected workflows still need their own plan, handoff, or observed evidence.",
    }


def _first_token(message: str) -> str:
    return message.strip().split(maxsplit=1)[0] if message.strip() else ""


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


def _action_from_spec(spec: dict[str, object]) -> dict[str, object]:
    return _action(
        str(spec.get("id", "")),
        str(spec.get("label", "")),
        str(spec.get("style", "")),
        enabled=bool(spec.get("enabled", True)),
        payload=spec.get("payload") if isinstance(spec.get("payload"), dict) else None,
    )


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
