from __future__ import annotations

import hashlib
from typing import Any

from ..ingress import CHAT_SOURCES, compact_source_metadata, extract_message_text, extract_source_metadata
from ..routing.catalog_questions import is_skill_catalog_question as _is_skill_catalog_question
from ..routing.chat import public_route_payload, route_chat_message
from ..coding_delegation import build_coding_delegation_payload
from ..context import build_context_brief
from ..executors import executor_label
from ..goal_loop import build_loop_start_card
from ..hermes_planning import build_hermes_plan_payload
from ..operator_productivity import build_agent_operator_productivity_card
from ..paths import OmhPaths, resolve_paths
from ..plugin_bundle.omh.awareness import workflow_context_card_for_workflow, workflow_context_cards
from ..probe import probe_capabilities
from ..quickstart import build_quickstart_card
from ..skills.catalog import installable_skill_definitions, primary_harness_for_skill, retained_delegation_skill_names
from ..visual_summary import image_generation_setup_fallback
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
CONTEXT_PRIMER_SCHEMA_VERSION = "omh_context_primer/v1"
USAGE_TRACE_SCHEMA_VERSION = "omh_usage_trace/v1"
WORKFLOW_EXPLANATION_SCHEMA_VERSION = "omh_workflow_explanation/v1"
MESSENGER_RENDERING_SCHEMA_VERSION = "omh_messenger_rendering/v1"
RENDER_PROFILE_LIMITED_MARKDOWN = "limited_markdown"
RENDER_PROFILE_RICH_MARKDOWN = "rich_markdown"
RENDER_PROFILES = (RENDER_PROFILE_LIMITED_MARKDOWN, RENDER_PROFILE_RICH_MARKDOWN)
_LIMITED_MARKDOWN_SOURCES = frozenset({"discord", "slack", "telegram"})
INTERACTION_MODES = ("auto", "route", "plan", "delegate")
VISIBLE_ACTIONS = (
    "answer:clarify",
    "show_command_preview",
    "show_skill_picker",
    "choose_skill",
    "search_skills",
    "accept_plan",
    "revise_plan",
    "present_plan",
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
    "show_quickstart",
    "show_context_brief",
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
    "show_research_department_plan",
    "revise_research_sources",
    "confirm_cadence_delivery_tooling",
    "record_source_observation",
    "prepare_paper_learning",
    "choose_explanation_level",
    "show_paper_source_requirements",
    "record_paper_metadata",
    "record_paper_excerpt_observed",
    "record_file_text_extraction_observed",
    "show_paper_learning",
    "continue_next_section",
    "revise_explanation_level",
    "show_coverage_ledger",
    "record_user_review",
    "prepare_visual_prompt_card",
    "show_visual_prompt_card",
    "copy_visual_prompt",
    "revise_visual_card",
    "change_visual_language",
    "choose_image_generator",
    "setup_image_generator",
    "generate_visual_image",
    "record_visual_image",
    "record_visual_qa",
    "record_visual_delivery",
    "show_visual_status",
    "run_hermes_research",
    "prepare_strategy_brief",
    "prepare_meeting_brief",
    "triage_feedback",
    "prepare_ops_review",
    "present_app_delivery_loop",
    "run_cto_loop",
    "prepare_deploy_monitor_plan",
    "prepare_review_or_followup_handoff",
    "run_local_operator_check",
    "prepare_operating_workflow",
    "prepare_memory_review",
    "prepare_coding_handoff",
    "prepare_coding_runtime_handoff",
    "prepare_operating_record",
    "prepare_report_package",
    "prepare_reliability_review",
    "prepare_scheduled_ops_blueprint",
    "prepare_research_department_plan",
    "prepare_material_package",
    "prepare_deliverable_package",
    "prepare_github_event_ops_card",
    "prepare_agent_board_card",
    "prepare_executor_runtime_readiness",
    "prepare_memory_curation_review",
    "prepare_gateway_intent_card",
    "prepare_voice_operator_card",
    "prepare_toolbelt_readiness",
    "prepare_ops_observability_card",
    "refresh_status",
    "prepare_agent_ops_review",
    "show_agent_ops_review",
    "choose_ops_lane",
    "prepare_research_lane",
    "prepare_coding_lane",
    "prepare_review_lane",
    "refresh_agent_ops_status",
    "record_agent_ops_observation",
    "record_workflow_learning_trace",
    "record_missed_route",
    "show_learning_review_queue",
    "show_learning_eval",
    "propose_skill_improvement",
    "review_improvement",
    "approve_improvement",
    "revise_improvement",
    "reject_improvement",
    "prepare_patch_proposal",
    "show_patch_proposal",
    "copy_patch_handoff",
    "add_regression_case",
    "audit_learning_readiness",
    "export_learning_bundle",
    "replay_regression_cases",
    "check_learning_index",
    "rebuild_learning_index",
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
    ("research-department", "Research Department", "Prepare Scout, Analyst, and Briefer research ops.", "./research-department <topic>"),
    ("paper-learning", "Paper Learning", "Explain a paper by level without dropping coverage.", "./paper-learning <paper>"),
    ("agent-ops-review", "Agent Ops Review", "See quality, blockers, next action, and throughput levers.", "./agent-ops-review <request>"),
    ("code-review", "Code Review", "Review completed work without overclaiming evidence.", "./code-review <scope>"),
    ("materials-package", "Materials Package", "Shape PPT, PDF, spreadsheet, document, or Markdown deliverables.", "./materials-package <brief>"),
    ("img-summary", "Img Summary", "Prepare image-generation-ready summary cards.", "./img-summary <source>"),
    ("automation-blueprint", "Automation Blueprint", "Prepare recurring Hermes scheduled-ops workflows.", "./automation-blueprint <intent>"),
    ("doctor", "Doctor", "Check OMH install and Hermes registration health.", "./doctor"),
)
_CONTEXT_PRIMER_GROUPS = (
    {
        "id": "intent_to_plan",
        "label": "Intent to plan",
        "workflows": ("deep-interview", "ralplan", "ultragoal", "loop", "ultraprocess"),
        "use_when": "The user has a fuzzy goal, a large goal, or one delivery cycle that needs research, planning, execution, review, and sync.",
    },
    {
        "id": "company_product_ops",
        "label": "Company and product ops",
        "workflows": ("feedback-triage", "research-department", "paper-learning", "web-research", "strategy-brief", "automation-blueprint"),
        "use_when": "The user needs customer-signal triage, source-backed research, recurring ops, meeting/report work, or strategy synthesis.",
    },
    {
        "id": "deliverables_and_visuals",
        "label": "Deliverables and visuals",
        "workflows": ("materials-package", "deliverable-package", "img-summary", "report-package"),
        "use_when": "The user wants files, decks, PDFs, reports, image-summary cards, or attachment-ready delivery states.",
    },
    {
        "id": "coding_and_runtime",
        "label": "Coding and runtime tracking",
        "workflows": ("idea-to-deploy", "agent-ops-review", "code-review", "ops-observability-card"),
        "use_when": "The user wants Hermes to prepare coding handoffs, explain executor status, review evidence, CI, or merge readiness.",
    },
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
_HUMAN_ACK_BODY_BY_SKILL = {
    "automation-blueprint": (
        "I will prepare this as a recurring Hermes ops workflow: schedule, source inputs, delivery target, "
        "silence policy, and the confirmation card. Creating the actual schedule or sending messages still "
        "needs observed runtime evidence."
    ),
    "research-department": (
        "I will shape this into a research workflow: what to watch, how raw findings move into analysis, "
        "how the briefing should be delivered, and what still needs source or delivery evidence."
    ),
    "paper-learning": (
        "I will explain this paper at the selected level without shrinking it into a short summary. I will first "
        "mark what paper text or PDF extraction is actually observed, then walk section by section with a coverage ledger."
    ),
    "materials-package": (
        "I will shape this into a material package: target files, source inputs, missing data, outline, "
        "generation owner, and QA checks. I will not claim the files exist until export evidence is observed."
    ),
    "deliverable-package": (
        "I will prepare the deliverable path: which files are needed, who generates them, what QA must pass, "
        "and how attachment or delivery status should be recorded."
    ),
    "github-event-ops": (
        "I will classify the GitHub PR, issue, review, or CI event into triage, review, label, or fix-handoff "
        "actions. Webhook delivery and GitHub mutations stay unobserved until a wrapper records them."
    ),
    "memory-curation-review": (
        "I will surface stale, duplicate, or conflicting memory and context candidates for approve, reject, or "
        "update choices. Nothing is written until approval is observed."
    ),
    "voice-operator": (
        "I will turn the short voice or mobile request into a concise clarify, plan, status, handoff, or "
        "confirmation card, and require confirmation before risky actions."
    ),
    "toolbelt-readiness": (
        "I will map the MCP, CLI, API, credential, and connector pieces this workflow needs, show what is "
        "observed versus missing, and suggest the safest setup or handoff next step."
    ),
    "web-research": (
        "I will keep this in Hermes as a source-backed research lane: define source boundaries, freshness, "
        "version or jurisdiction scope, citation confidence, and retrieval gaps before any later plan or handoff."
    ),
    "strategy-brief": (
        "I will prepare strategy options, tradeoffs, decision notes, and open questions in Hermes. Implementation "
        "handoff stays disabled until an accepted decision creates explicit work."
    ),
    "meeting-brief": (
        "I will prepare the agenda, context prompts, decision slots, and follow-up template. Prepared meeting "
        "material is not evidence that the meeting happened."
    ),
    "feedback-triage": (
        "I will cluster the signal, separate bug reports, requests, and questions, and recommend the next investigation, "
        "plan, or handoff path without treating triage as implementation."
    ),
    "code-review": (
        "I will prepare the review path: what needs checking, which claims need evidence, and what follow-up handoff "
        "is needed if fixes are found. Review preparation is not a completed review."
    ),
    "report-package": (
        "I will prepare the report package: source inputs, outline, missing numbers, approval points, and export or "
        "delivery checks. The package is not delivered until observed evidence exists."
    ),
    "reliability-review": (
        "I will prepare a reliability review with service boundaries, SLO or incident context, risk areas, and "
        "remediation handoff options. Healthy status or incident closure still needs observed evidence."
    ),
    "gateway-intent-card": (
        "I will normalize the gateway intent: origin, thread, delivery policy, silent updates, attachments, and "
        "status-update behavior before any platform action is claimed."
    ),
    "ops-observability-card": (
        "I will prepare a wrapper-safe observability card for token, cost, latency, run history, and failure-mode "
        "signals while keeping local estimates separate from provider-observed truth."
    ),
    "operating-rhythm": (
        "I will prepare the operating rhythm: cadence, meeting topics, decision records, owners, and follow-up "
        "slots. Prepared operations notes are not evidence that the work happened."
    ),
}

_ACK_PRIMARY_ACTIONS_BY_NEXT_ACTION = {
    "present_plan": ("present_plan", "Show plan"),
    "assess_loopability": ("assess_loopability", "Assess loopability"),
    "prepare_visual_prompt_card": ("prepare_visual_prompt_card", "Prepare image card"),
    "prepare_agent_ops_review": ("prepare_agent_ops_review", "Open ops review"),
    "start_ultraprocess": ("start_ultraprocess", "Start ultraprocess"),
    "audit_learning_readiness": ("audit_learning_readiness", "Audit learning"),
    "run_hermes_research": ("run_hermes_research", "Start research"),
    "prepare_strategy_brief": ("prepare_strategy_brief", "Prepare strategy"),
    "prepare_meeting_brief": ("prepare_meeting_brief", "Prepare brief"),
    "triage_feedback": ("triage_feedback", "Triage feedback"),
    "prepare_ops_review": ("prepare_ops_review", "Prepare ops review"),
    "present_app_delivery_loop": ("present_app_delivery_loop", "Show delivery loop"),
    "run_cto_loop": ("run_cto_loop", "Open team loop"),
    "prepare_deploy_monitor_plan": ("prepare_deploy_monitor_plan", "Prepare deploy plan"),
    "prepare_review_or_followup_handoff": ("prepare_review_or_followup_handoff", "Prepare review"),
    "run_local_operator_check": ("run_local_operator_check", "Show local check"),
    "prepare_operating_workflow": ("prepare_operating_workflow", "Prepare workflow"),
    "prepare_memory_review": ("prepare_memory_review", "Review memory"),
    "prepare_coding_handoff": ("prepare_coding_handoff", "Prepare coding handoff"),
    "prepare_coding_runtime_handoff": ("prepare_coding_runtime_handoff", "Prepare runtime handoff"),
    "prepare_operating_record": ("prepare_operating_record", "Prepare rhythm"),
    "prepare_report_package": ("prepare_report_package", "Prepare report"),
    "prepare_reliability_review": ("prepare_reliability_review", "Review reliability"),
    "prepare_scheduled_ops_blueprint": ("prepare_scheduled_ops_blueprint", "Prepare automation"),
    "prepare_research_department_plan": ("prepare_research_department_plan", "Prepare research flow"),
    "prepare_paper_learning": ("prepare_paper_learning", "Prepare paper learning"),
    "prepare_material_package": ("prepare_material_package", "Prepare package"),
    "prepare_deliverable_package": ("prepare_deliverable_package", "Prepare deliverable"),
    "prepare_github_event_ops_card": ("prepare_github_event_ops_card", "Open event card"),
    "prepare_agent_board_card": ("prepare_agent_board_card", "Open agent board"),
    "prepare_executor_runtime_readiness": ("prepare_executor_runtime_readiness", "Check runtime"),
    "prepare_memory_curation_review": ("prepare_memory_curation_review", "Review memory"),
    "prepare_gateway_intent_card": ("prepare_gateway_intent_card", "Open gateway card"),
    "prepare_voice_operator_card": ("prepare_voice_operator_card", "Open voice card"),
    "prepare_toolbelt_readiness": ("prepare_toolbelt_readiness", "Check toolbelt"),
    "prepare_ops_observability_card": ("prepare_ops_observability_card", "Open observability"),
    "refresh_status": ("refresh_status", "Refresh status"),
}


def _ack_actions_for_next_action(next_action: str) -> list[dict[str, object]]:
    actions: list[dict[str, object]] = []
    primary = _ACK_PRIMARY_ACTIONS_BY_NEXT_ACTION.get(next_action)
    if primary:
        actions.append(_action(primary[0], primary[1], "primary"))
    status_action = "show_memory_status" if next_action == "prepare_memory_curation_review" else "show_status"
    status_label = "Show memory status" if status_action == "show_memory_status" else "Show status"
    actions.append(_action(status_action, status_label, "secondary"))
    return actions


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
    paths: OmhPaths | None = None,
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
    route_payload = public_route_payload(route, include_message=include_message)
    if _is_generic_skill_catalog_route(message, route_payload):
        route_payload = _catalog_question_route_payload(route_payload)
    base["route"] = route_payload
    if isinstance(route_payload.get("task_card"), dict):
        base["task_card"] = route_payload["task_card"]

    if _is_omh_intro_question(message) and resolved_mode in {"route", "plan", "clarify"}:
        base["mode"] = "route"
        base["route"] = _omh_intro_route_payload(route_payload)
        base["chat_response"] = build_chat_response_from_omh_context_brief(
            message,
            source=source,
            thread_key=str(base["thread_key"]),
        )
        base["next_action"] = str(_nested(base["chat_response"], "state").get("next_action", "show_context_brief"))
        return _finish_interaction(base, target_notice)

    if _is_omh_quickstart_question(message) and resolved_mode in {"route", "plan", "clarify"}:
        base["mode"] = "status"
        base["route"] = _omh_quickstart_route_payload(route_payload)
        base["chat_response"] = build_chat_response_from_omh_quickstart(
            paths or resolve_paths(),
            source=source,
            thread_key=str(base["thread_key"]),
        )
        base["next_action"] = str(_nested(base["chat_response"], "state").get("next_action", "show_quickstart"))
        return _finish_interaction(base, target_notice)

    if (
        _is_omh_status_question(message)
        and str(route_payload.get("selected_skill", "")) == _ROUTER_SKILL
        and resolved_mode in {"route", "plan", "clarify"}
    ):
        base["mode"] = "status"
        base["route"] = _omh_status_route_payload(route_payload)
        base["chat_response"] = build_chat_response_from_omh_status_roadmap(
            paths or resolve_paths(),
            thread_key=str(base["thread_key"]),
        )
        base["next_action"] = str(_nested(base["chat_response"], "state").get("next_action", "show_status"))
        return _finish_interaction(base, target_notice)

    if resolved_mode == "route" and _is_command_preview_invocation(message):
        base["chat_response"] = build_chat_response_from_route(
            route_payload,
            thread_key=str(base["thread_key"]),
            message=message,
            include_message=include_message,
        )
        base["next_action"] = str(_nested(base["chat_response"], "state").get("next_action", "show_command_preview"))
        return _finish_interaction(base, target_notice)

    if resolved_mode == "clarify" or route["action"] != "dispatch":
        base["chat_response"] = build_chat_response_from_route(
            route_payload,
            thread_key=str(base["thread_key"]),
            message=message,
            include_message=include_message,
        )
        base["next_action"] = str(_nested(base["chat_response"], "state").get("next_action", "answer_clarification"))
        return _finish_interaction(base, target_notice)

    if resolved_mode == "route":
        base["chat_response"] = build_chat_response_from_route(
            route_payload,
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
    return _finish_interaction(payload, None)


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
    if _is_generic_skill_catalog_route(message, decision):
        return _skill_picker_response(decision, thread_key=thread_key, message=message)
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
        workflow_explanation_reason = _workflow_explanation_reason_for_route(decision, policy, selected)
        task_card = _route_task_card(decision)
        if task_card and str(task_card.get("task_type", "")) != "router_design_feedback":
            return _chat_response_from_task_card(
                task_card,
                decision=decision,
                thread_key=thread_key,
                workflow_explanation_reason=workflow_explanation_reason,
            )
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
                    "workflow_explanation_reason": workflow_explanation_reason,
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
                    "workflow_explanation_reason": workflow_explanation_reason,
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
        if selected == "img-summary" or policy_next_action == "prepare_visual_prompt_card":
            evidence_boundary = str(policy.get("evidence_boundary", "")) or "A prepared image-card brief is not generated image evidence."
            body = (
                "I will turn the source into a shareable image-card brief: audience, layout, on-image copy, "
                "generation prompt, negative prompt, and a quick QA checklist. If no image tool is connected, "
                "I will ask which tool to use instead of pretending an image was generated."
            )
            return _chat_response(
                kind="img_summary",
                headline="I can prepare a shareable image card for this.",
                body=body,
                phase="visual_prompt_prepared",
                next_action="prepare_visual_prompt_card",
                thread_key=thread_key,
                actions=[
                    _action("show_visual_prompt_card", "Show card", "primary"),
                    _action("copy_visual_prompt", "Copy prompt", "secondary"),
                    _action("revise_visual_card", "Revise card", "secondary"),
                    _action("change_visual_language", "Change language", "secondary"),
                    _action("choose_image_generator", "Choose image tool", "secondary"),
                    _action("setup_image_generator", "Set up image tool", "secondary"),
                    _action("record_visual_image", "Record generated image", "secondary"),
                    _action("record_visual_qa", "Record visual QA", "secondary"),
                    _action("record_visual_delivery", "Record delivery", "secondary"),
                    _action("show_visual_status", "Show visual status", "secondary"),
                ],
                claim_boundary=evidence_boundary,
                extra_state={
                    "route_action": action,
                    "confidence": decision.get("confidence", "low"),
                    "selected_workflow": selected,
                    "workflow_explanation_reason": workflow_explanation_reason,
                    "policy_next_action": policy_next_action,
                    "artifact_schema": "visual_prompt_card/v1",
                    "observation_schema": "visual_observation/v1",
                    "image_generation_capability": "unknown",
                    "image_generation_setup": image_generation_setup_fallback("unknown"),
                    "evidence_not_observed": [
                        "image generation",
                        "visual QA",
                        "sharing",
                        "posting",
                        "attachment",
                        "delivery",
                    ],
                    "capability_action_rule": (
                        "Show generate_visual_image only when wrapper context reports image_generation_capability/v1 "
                        "with state connected; that action is still not generation evidence."
                    ),
                },
            )
        if selected == "agent-ops-review" or policy_next_action == "prepare_agent_ops_review":
            evidence_boundary = str(policy.get("evidence_boundary", "")) or "An agent ops review card is not runtime evidence."
            card = build_agent_operator_productivity_card(
                message or selected,
                source=str(decision.get("source", "generic")),
            )
            status_card = card["status_card"]
            return _chat_response(
                kind="agent_ops_review",
                headline=str(status_card.get("headline", "I can prepare an agent ops review for this.")),
                body=(
                    "I will show quality gates, current gaps, blockers, next actions, and throughput levers "
                    "without asking the user to approve shell catalog commands."
                ),
                phase="agent_ops_review_prepared",
                next_action=str(card.get("next_action", "show_agent_ops_review")),
                thread_key=thread_key,
                actions=[
                    _action("show_agent_ops_review", "Show agent ops review", "primary"),
                    _action("prepare_research_lane", "Prepare research lane", "secondary"),
                    _action("prepare_coding_lane", "Prepare coding lane", "secondary"),
                    _action("prepare_review_lane", "Prepare review lane", "secondary"),
                    _action("refresh_agent_ops_status", "Refresh status", "secondary"),
                    _action("record_agent_ops_observation", "Record observation", "secondary"),
                ],
                claim_boundary=evidence_boundary,
                extra_state={
                    "route_action": action,
                    "confidence": decision.get("confidence", "low"),
                    "selected_workflow": selected,
                    "workflow_explanation_reason": workflow_explanation_reason,
                    "policy_next_action": policy_next_action,
                    "artifact_schema": card["schema_version"],
                    "status_card_schema": status_card.get("schema_version", ""),
                    "agent_ops_review": card,
                    "quality_state": status_card.get("quality_state", "prepared_not_observed"),
                    "blockers": status_card.get("blockers", []),
                    "throughput_levers": card.get("throughput_levers", []),
                    "evidence_not_observed": card.get("not_evidence_until_observed", []),
                },
            )
        if selected == "workflow-learning":
            missed_route_feedback = _is_missed_route_feedback(message)
            primary_learning_action = "record_missed_route" if missed_route_feedback else "audit_learning_readiness"
            headline = (
                "I can record this missed OMH route."
                if missed_route_feedback
                else "I can inspect this workflow for learning readiness."
            )
            evidence_boundary = str(policy.get("evidence_boundary", "")) or (
                "Workflow learning records are process-review evidence only; they are not automatic improvement evidence."
            )
            if missed_route_feedback:
                body = (
                    "I will treat this as missed-route feedback: record a metadata-only trace, create a reviewable "
                    "missed-route bundle, add or request a minimized regression fixture, and keep any routing or skill "
                    "change behind human review."
                )
            else:
                body = (
                    "I will turn the workflow attempt into learning material without storing raw prompts: "
                    "record the trace, run deterministic evals, add a regression case, audit readiness, "
                    "and export a redacted review bundle when useful. Any skill or routing improvement still needs human review."
                )
            return _chat_response(
                kind="workflow_learning",
                headline=headline,
                body=body,
                phase="workflow_learning_prepared",
                next_action=primary_learning_action,
                thread_key=thread_key,
                actions=[
                    _action("record_missed_route", "Record missed route", "primary" if missed_route_feedback else "secondary"),
                    _action("record_workflow_learning_trace", "Record trace", "secondary"),
                    _action("show_learning_review_queue", "Review queue", "secondary"),
                    _action("show_learning_eval", "Run eval", "secondary"),
                    _action("propose_skill_improvement", "Propose improvement", "secondary"),
                    _action("review_improvement", "Review improvement", "secondary"),
                    _action("prepare_patch_proposal", "Prepare patch proposal", "secondary"),
                    _action("show_patch_proposal", "Show patch proposal", "secondary"),
                    _action("copy_patch_handoff", "Copy patch handoff", "secondary"),
                    _action("add_regression_case", "Add regression", "secondary"),
                    _action("audit_learning_readiness", "Audit readiness", "secondary" if missed_route_feedback else "primary"),
                    _action("export_learning_bundle", "Export bundle", "secondary"),
                    _action("replay_regression_cases", "Replay cases", "secondary"),
                    _action("check_learning_index", "Check index", "secondary"),
                    _action("rebuild_learning_index", "Rebuild index", "secondary"),
                    _action("show_status", "Show status", "secondary"),
                ],
                claim_boundary=evidence_boundary,
                extra_state={
                    "route_action": action,
                    "confidence": decision.get("confidence", "low"),
                    "selected_workflow": selected,
                    "workflow_explanation_reason": workflow_explanation_reason,
                    "policy_next_action": policy_next_action,
                    "learning_intent": "missed_route" if missed_route_feedback else "readiness_audit",
                    "primary_learning_action": primary_learning_action,
                    "artifact_schemas": [
                        "workflow_learning_trace/v1",
                        "workflow_eval_result/v1",
                        "learning_missed_route_result/v1",
                        "regression_case/v1",
                        "improvement_candidate/v1",
                        "improvement_candidate_review_card/v1",
                        "improvement_patch_proposal/v1",
                        "workflow_learning_review_queue/v1",
                        "workflow_learning_audit/v1",
                        "learning_audit_card/v1",
                        "workflow_learning_export/v1",
                    ],
                    "learning_audit_card_schema": "learning_audit_card/v1",
                    "learning_review_queue_schema": "workflow_learning_review_queue/v1",
                    "improvement_candidate_review_card_schema": "improvement_candidate_review_card/v1",
                    "human_gate_required": True,
                    "evidence_not_observed": [
                        "raw prompt storage",
                        "model training",
                        "automatic skill patch",
                        "workflow execution",
                        "future behavior fixed",
                        "review approval",
                        "CI",
                        "merge",
                    ],
                    "learning_flow": [
                        "record_trace",
                        "record_missed_route",
                        "run_eval",
                        "add_regression_case",
                        "review_queue",
                        "review_improvement_candidate",
                        "prepare_patch_proposal",
                        "audit_readiness",
                        "export_redacted_bundle",
                        "human_review_improvement_candidate",
                    ],
                    **_task_card_state(decision),
                },
            )
        next_action = policy_next_action if policy_next_action and policy_next_action != "show_workflow_guidance" else "dispatch_to_workflow"
        wrapper_guidance = str(policy.get("wrapper_guidance", ""))
        evidence_boundary = str(policy.get("evidence_boundary", "")) or "Routing is not execution evidence."
        body = _HUMAN_ACK_BODY_BY_SKILL.get(
            selected,
            wrapper_guidance or f"I will prepare a safe next step for `{selected}` before claiming any work happened.",
        )
        return _chat_response(
            kind="ack",
            headline="I know which workflow should handle this.",
            body=body,
            phase="routed",
            next_action=next_action,
            thread_key=thread_key,
            actions=_ack_actions_for_next_action(next_action),
            claim_boundary=evidence_boundary,
            extra_state={
                "route_action": action,
                "confidence": decision.get("confidence", "low"),
                "selected_workflow": selected,
                "workflow_explanation_reason": workflow_explanation_reason,
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
    if action == "fallback" and _is_file_lookup_fallback(decision):
        return _chat_response(
            kind="clarification",
            headline="This looks like a file or text lookup.",
            body=str(
                decision.get("clarification")
                or "Answer this as a file or text lookup, or ask for the target file/path if it is missing."
            ),
            phase="clarifying",
            next_action="answer_file_lookup",
            thread_key=thread_key,
            actions=[
                _action("answer:file_lookup", "Answer file lookup", "primary"),
                _action("cancel", "Cancel", "secondary"),
            ],
            claim_boundary="No OMH workflow, execution, or file inspection has started.",
            extra_state={
                "route_action": action,
                "confidence": decision.get("confidence", "low"),
                "lookup_kind": "file_or_text",
                "routing_instruction": decision.get("routing_instruction", ""),
            },
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


def _is_file_lookup_fallback(decision: dict[str, object]) -> bool:
    text = " ".join(
        str(decision.get(key, "") or "")
        for key in ("reason", "clarification", "routing_instruction")
    ).lower()
    return "file or text lookup" in text or "file/text lookup" in text


def _route_task_card(decision: dict[str, object]) -> dict[str, object]:
    task_card = decision.get("task_card")
    return dict(task_card) if isinstance(task_card, dict) else {}


def _task_card_state(decision: dict[str, object]) -> dict[str, object]:
    task_card = _route_task_card(decision)
    return {"task_card": task_card} if task_card else {}


def _chat_response_from_task_card(
    task_card: dict[str, object],
    *,
    decision: dict[str, object],
    thread_key: str,
    workflow_explanation_reason: str,
) -> dict[str, object]:
    task_type = str(task_card.get("task_type", "task")).replace("_", " ")
    next_action = str(task_card.get("recommended_next_action", "prepare_agent_ops_review"))
    rails = _task_card_rails(task_card)
    risk_domains = _string_items(task_card.get("risk_domains", []))
    primitives = _string_items(task_card.get("operation_primitives", []))
    evidence_boundary = _nested(task_card, "evidence_boundary")
    not_observed = _string_items(evidence_boundary.get("not_observed", []))
    secret_policy = _nested(task_card, "secret_policy")
    gateway_transfer = _nested(task_card, "gateway_transfer")
    first_safe_action = str(task_card.get("first_safe_action", "")).strip()
    secret_action = str(secret_policy.get("recommended_action", "")).strip()
    invariant = str(gateway_transfer.get("invariant", "")).strip().replace("_", " ")

    body_lines = [
        f"This is a {task_type} task, not a migration workflow.",
        f"First safe action: {first_safe_action}" if first_safe_action else "",
        f"Use workflow rails: {', '.join(rails[:4])}." if rails else "",
        f"Track primitives: {', '.join(_display_items(primitives[:7]))}." if primitives else "",
        f"Risks to surface: {', '.join(_display_items(risk_domains[:5]))}." if risk_domains else "",
        f"Secret policy: {secret_action}." if secret_action else "",
        f"Gateway invariant: {invariant}." if invariant else "",
        f"Not observed yet: {', '.join(_display_items(not_observed[:4]))}." if not_observed else "",
    ]
    body = " ".join(line for line in body_lines if line)
    return _chat_response(
        kind="task_card",
        headline="I will frame this as a high-level task first.",
        body=body,
        phase="task_card_prepared",
        next_action=next_action,
        thread_key=thread_key,
        actions=[
            _action(next_action, _label_for_action(next_action), "primary"),
            _action("show_status", "Show status", "secondary"),
            _action("record_workflow_learning_trace", "Record learning trace", "secondary"),
        ],
        claim_boundary=str(task_card.get("claim_boundary", "A prepared task card is not observed execution evidence.")),
        extra_state={
            "route_action": decision.get("action", "dispatch"),
            "confidence": decision.get("confidence", "low"),
            "selected_workflow": decision.get("selected_skill", ""),
            "workflow_explanation_reason": workflow_explanation_reason,
            "task_card": task_card,
            "task_type": task_card.get("task_type", ""),
            "route_level": task_card.get("route_level", ""),
            "workflow_rails": task_card.get("workflow_rails", []),
            "operation_primitives": primitives,
            "risk_domains": risk_domains,
            "evidence_not_observed": not_observed,
        },
    )


def _task_card_rails(task_card: dict[str, object]) -> list[str]:
    rails: list[str] = []
    raw_rails = task_card.get("workflow_rails", [])
    if not isinstance(raw_rails, list):
        return rails
    for rail in raw_rails:
        if isinstance(rail, dict):
            skill = str(rail.get("skill", "")).strip()
            if skill:
                rails.append(skill)
    return rails


def _string_items(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _display_items(items: list[str]) -> list[str]:
    return [item.replace("_", " ") for item in items]


def _label_for_action(action_id: str) -> str:
    for known_action, label in _ACK_PRIMARY_ACTIONS_BY_NEXT_ACTION.values():
        if known_action == action_id:
            return label
    return action_id.replace("_", " ").title()


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
                "executor_readiness": delegation_payload.get("executor_readiness", {}),
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
                "executor_readiness": delegation_payload.get("executor_readiness", {}),
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
                "executor_readiness": delegation_payload.get("executor_readiness", {}),
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
                "executor_readiness": delegation_payload.get("executor_readiness", {}),
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
    kind, headline, body, claim_boundary = _status_copy(status_payload, next_action)
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


def build_chat_response_from_omh_status_roadmap(paths: OmhPaths, *, thread_key: str = "") -> dict[str, object]:
    probe = probe_capabilities(paths, include_roadmap=True)
    roadmap = _nested(probe, "capability_gap_roadmap")
    summary = _nested(roadmap, "summary")
    next_actions = _roadmap_next_actions(roadmap, limit=3)
    setup_gaps = _intish(summary.get("baseline_product_gaps", 0))
    evidence_gaps = _intish(summary.get("evidence_gaps", 0))
    optional_unknowns = _intish(summary.get("optional_or_host_unknowns", 0))
    next_action_sentence = _section_item_without_next_prefix(_roadmap_next_action_sentence(next_actions))
    body_lines = [
        "Current status:",
        f"- OMH setup gaps: {setup_gaps}.",
        f"- Evidence gaps: {evidence_gaps}.",
        f"- Optional/host unknowns: {optional_unknowns}.",
        "",
        "Next action:",
        f"- {next_action_sentence}" if next_action_sentence else "- No immediate local action is required.",
        "",
        "Boundary: local setup, plugin install, or smoke checks are not proof that Hermes loaded the plugin, ran an executor, reviewed code, passed CI, or merged anything.",
    ]
    return _chat_response(
        kind="status",
        headline="Here is the current OMH status and next action.",
        body="\n".join(body_lines),
        phase="status",
        next_action="show_status",
        thread_key=thread_key,
        actions=[
            _action("show_status", "Show status", "primary"),
            _action("show_target_status", "Show target status", "secondary"),
        ],
        claim_boundary=str(roadmap.get("claim_boundary") or probe.get("claim_boundary") or _default_overclaim_guard()),
        extra_state={
            "status_source": "omh_probe",
            "probe_summary": {
                "plugin_distribution_ready": bool(probe.get("plugin_distribution_ready")),
                "plugin_runtime_active": bool(probe.get("plugin_runtime_active")),
                "native_integration_claim_ready": bool(probe.get("native_integration_claim_ready")),
                "team_worker_readiness_ready": bool(probe.get("team_worker_readiness_ready")),
                "mcp_host_session_observed": bool(probe.get("mcp_host_session_observed")),
            },
            "capability_gap_roadmap": roadmap,
            "roadmap_next_actions": next_actions,
            "workflow_explanation_reason": "The user asked for OMH status or the next operational action, so the wrapper shows local probe and roadmap evidence instead of drafting a new plan.",
            "evidence_not_observed": [
                "Hermes plugin runtime load",
                "wrapper-visible workflow use",
                "executor work",
                "review, CI, or merge",
            ],
        },
    )


def build_chat_response_from_omh_quickstart(
    paths: OmhPaths,
    *,
    source: str = "generic",
    thread_key: str = "",
) -> dict[str, object]:
    card = build_quickstart_card(paths, source=source)
    local_status = _nested(card, "local_status")
    doctor = _nested(local_status, "doctor")
    plugin_bridge = _nested(local_status, "plugin_bridge")
    wrapper_usage = _nested(local_status, "wrapper_usage")
    prompts = card.get("chat_prompts", [])
    first_prompt = ""
    if isinstance(prompts, list) and prompts and isinstance(prompts[0], dict):
        first_prompt = str(prompts[0].get("prompt", "")).strip()
    evidence_gaps = card.get("not_evidence_yet", [])
    evidence_gap = str(evidence_gaps[0]) if isinstance(evidence_gaps, list) and evidence_gaps else _default_overclaim_guard()
    roadmap = _nested(card, "capability_gap_roadmap")
    next_actions = _roadmap_next_actions(roadmap, limit=3)

    body_lines = [
        (
            f"OMH quickstart is {card.get('status', 'unknown')}: "
            f"{doctor.get('passing', 0)}/{doctor.get('total', 0)} local checks pass."
        ),
        "",
        "Local status:",
        f"- Plugin bridge: {str(plugin_bridge.get('status', 'unknown')).replace('_', ' ')}.",
        f"- Hermes plugin use: {'observed' if bool(local_status.get('plugin_runtime_active')) else 'not observed yet'}.",
        f"- Wrapper usage: {str(wrapper_usage.get('status', 'missing')).replace('_', ' ')}.",
        "",
        "Next in Hermes:",
        f"- {first_prompt}" if first_prompt else "- Ask Hermes what you want to do with OMH.",
        "- Open the workflow picker with ./omh when you want to choose manually.",
        "- Use Show detailed status only when setup or registration looks wrong.",
        "",
        f"Boundary: {evidence_gap}",
    ]
    observed_gaps = [str(item) for item in evidence_gaps if str(item)] if isinstance(evidence_gaps, list) else []
    return _chat_response(
        kind="quickstart",
        headline="Here is the OMH first-use path.",
        body="\n".join(body_lines),
        phase="status",
        next_action="show_quickstart",
        thread_key=thread_key,
        actions=[
            _action("show_quickstart", "Show quickstart", "primary"),
            _action("show_skill_picker", "Open workflow picker", "secondary"),
            _action("show_status", "Show detailed status", "secondary"),
        ],
        claim_boundary=str(card.get("claim_boundary") or _default_overclaim_guard()),
        extra_state={
            "status_source": "omh_quickstart",
            "quickstart_card": card,
            "capability_gap_roadmap": roadmap,
            "roadmap_next_actions": next_actions,
            "workflow_explanation_reason": "The user asked what to do after OMH setup or install, so the wrapper shows the first-use quickstart card instead of asking for shell command approval.",
            "evidence_not_observed": observed_gaps,
        },
    )


def build_chat_response_from_omh_context_brief(
    message: str = "",
    *,
    source: str = "generic",
    thread_key: str = "",
) -> dict[str, object]:
    brief = build_context_brief(message, source=source, max_hints=2, include_prompt_context=False)
    lanes = brief.get("lanes", [])
    lane_summaries: list[str] = []
    if isinstance(lanes, list):
        for lane in lanes[:4]:
            if not isinstance(lane, dict):
                continue
            label = str(lane.get("label", "")).strip()
            use_for = str(lane.get("use_for", "")).strip()
            if label and use_for:
                lane_summaries.append(f"{label}: {use_for}")
    body_lines = [
        "OMH is the Hermes workflow layer: install once, then ask Hermes in chat instead of memorizing backend commands.",
        "",
        "Use it for:",
        *[f"- {summary}" for summary in lane_summaries[:3]],
        "",
        "How to start:",
        "- Ask what you want in normal language.",
        "- Open the workflow picker with ./omh when you want to choose manually.",
        "- Ask what to do next after setup when you want the first-use path.",
        "",
        "Boundary: this context explains routing and workflow choices; it is not execution, delivery, verification, review, CI, or merge evidence.",
    ]
    return _chat_response(
        kind="context_brief",
        headline="Here is how OMH fits into Hermes.",
        body="\n".join(body_lines),
        phase="route",
        next_action="show_context_brief",
        thread_key=thread_key,
        actions=[
            _action("show_context_brief", "Show OMH overview", "primary"),
            _action("show_skill_picker", "Open workflow picker", "secondary"),
            _action("show_quickstart", "Show quickstart", "secondary"),
        ],
        claim_boundary=str(brief.get("claim_boundary") or _default_overclaim_guard()),
        extra_state={
            "status_source": "omh_context_brief",
            "context_brief": brief,
            "workflow_explanation_reason": "The user asked what OMH is or how to use it, so the wrapper explains the Hermes-facing mental model before opening the full picker.",
            "evidence_not_observed": [
                "workflow selection",
                "plan acceptance",
                "executor dispatch",
                "generation, delivery, verification, review, CI, or merge",
            ],
        },
    )


def build_status_card_from_status(status_payload: dict[str, Any]) -> dict[str, object]:
    next_action = str(status_payload.get("next_action", "show_status"))
    kind, headline, body, claim_boundary = _status_copy(status_payload, next_action)
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


def _status_copy(status_payload: dict[str, Any], next_action: str) -> tuple[str, str, str, str]:
    fallback = (
        "status",
        "I have a conservative status update.",
        str(status_payload.get("safe_summary", "")),
        "Only observed evidence can support completion claims.",
    )
    kind, headline, body, claim_boundary = _STATUS_COPY.get(next_action, fallback)
    if next_action == "wait_for_executor_evidence":
        label = _status_executor_label(status_payload)
        suffix = f" ({label})" if label else ""
        return (
            kind,
            f"The coding handoff{suffix} was dispatched.",
            f"I am waiting for {label + ' ' if label else ''}executor evidence before reporting completion.",
            claim_boundary,
        )
    if next_action == "dispatch_to_executor":
        label = _status_executor_label(status_payload)
        suffix = f" ({label})" if label else ""
        return (
            kind,
            f"The coding handoff{suffix} is ready.",
            "I have prepared the coding handoff, but executor/runtime dispatch is not observed yet.",
            claim_boundary,
        )
    return kind, headline, body, claim_boundary


def _status_executor_label(status_payload: dict[str, Any]) -> str:
    for value in (
        _nested(status_payload, "prepared").get("executor_target", ""),
        _nested(status_payload, "prepared").get("selected_executor_profile", ""),
        _nested(status_payload, "executor_session_status").get("selected_executor_profile", ""),
        status_payload.get("selected_executor_profile", ""),
    ):
        profile = str(value or "").strip()
        if profile:
            return executor_label(profile)
    return ""


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
    if target_notice:
        payload["target_notice"] = target_notice
        topology = target_notice.get("topology")
        if isinstance(topology, dict):
            payload["target_topology"] = topology
    response = payload.get("chat_response")
    if isinstance(response, dict):
        if target_notice:
            response = _chat_response_with_target_notice(response, target_notice)
        payload["chat_response"] = _chat_response_with_render_profile(
            response,
            source=str(payload.get("source", "generic")),
            source_metadata=_nested(payload, "source_metadata"),
        )
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
    raw_actions = updated.get("actions", [])
    actions = [action for action in raw_actions if isinstance(action, dict)] if isinstance(raw_actions, list) else []
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
    trace = updated.get("usage_trace")
    visible_prefix = str(trace.get("visible_prefix", "")) if isinstance(trace, dict) else ""
    if visible_prefix:
        updated["messenger_rendering"] = messenger_rendering_contract(
            visible_prefix=visible_prefix,
            first_line=str(updated.get("headline", "")),
            body=str(updated.get("body", "")),
            claim_boundary=str(updated.get("claim_boundary", "")),
        )
    return updated


def _chat_response_with_render_profile(
    response: dict[str, object],
    *,
    source: str,
    source_metadata: dict[str, object],
) -> dict[str, object]:
    updated = dict(response)
    trace = updated.get("usage_trace")
    visible_prefix = str(trace.get("visible_prefix", "")) if isinstance(trace, dict) else ""
    if visible_prefix:
        updated["messenger_rendering"] = messenger_rendering_contract(
            visible_prefix=visible_prefix,
            first_line=str(updated.get("headline", "")),
            body=str(updated.get("body", "")),
            claim_boundary=str(updated.get("claim_boundary", "")),
            render_profile=render_profile_for_source(source, source_metadata),
        )
    return updated


def _resolve_mode(mode: str, route: dict[str, object], *, message: str = "") -> str:
    if mode != "auto":
        return mode
    if _is_command_preview_invocation(message):
        return "route"
    if _is_skill_catalog_question(message):
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


def _is_missed_route_feedback(message: str) -> bool:
    text = " ".join(message.lower().split())
    compact = text.replace(" ", "")
    if not text:
        return False
    missed_route_phrases = (
        "missed route",
        "missed workflow",
        "missing route",
        "wrong route",
        "wrong workflow",
        "did not use omh",
        "didn't use omh",
        "didnt use omh",
        "not use omh",
        "skipped omh",
        "omh was not used",
        "omh was skipped",
        "expected omh",
        "expected workflow",
    )
    if any(phrase in text for phrase in missed_route_phrases):
        return True
    missed_route_compact_phrases = (
        "omh안썼",
        "omh안썻",
        "omh안썼어",
        "omh안썻어",
        "omh안쓰",
        "omh를안썼",
        "omh를안썻",
        "omh를안쓰",
        "omh기능안썼",
        "omh기능안썻",
        "omh기능안쓰",
        "omh안씀",
        "omh누락",
        "워크플로누락",
        "라우팅누락",
        "잘못라우팅",
    )
    return any(phrase in compact for phrase in missed_route_compact_phrases)


def _workflow_explanation_reason_for_route(
    decision: dict[str, object],
    policy: dict[str, object],
    selected: str,
) -> str:
    guidance = str(policy.get("wrapper_guidance") or "").strip()
    if guidance:
        return f"Selected `{selected}` because this request matches that workflow's triggers. {guidance}"
    reason = str(decision.get("reason") or "").strip()
    if reason and reason != "Matched trigger metadata for this task.":
        return reason
    return ""


def _is_generic_skill_catalog_route(message: str, decision: dict[str, object]) -> bool:
    if not _is_skill_catalog_question(message):
        return False
    return str(decision.get("selected_skill", "")) == _ROUTER_SKILL


def _catalog_question_route_payload(route_payload: dict[str, object]) -> dict[str, object]:
    updated = dict(route_payload)
    harness = primary_harness_for_skill(_ROUTER_SKILL)
    updated.update(
        {
            "action": "dispatch",
            "ambiguous": False,
            "candidate_harness": harness,
            "candidate_skill": _ROUTER_SKILL,
            "confidence": "high",
            "reason": "Catalog question; show the OMH workflow picker instead of asking for shell command approval.",
            "recommendations": [
                {
                    "confidence": "high",
                    "evidence_boundary": "Skill picker routing is not plan acceptance, dispatch, execution, review, CI, or verification evidence.",
                    "matched": ["catalog_question"],
                    "next_action": "choose_skill",
                    "score": max(10, _intish(updated.get("score", 0))),
                    "skill": _ROUTER_SKILL,
                    "wrapper_guidance": "Render the OMH workflow picker in chat; do not ask the user to approve `omh list` for catalog discovery.",
                }
            ],
            "routing_instruction": "Show the OMH workflow picker for this catalog question.",
            "routing_prompt_template": "Show the OMH workflow picker for this catalog question.\n\nUser message:\n{message}",
            "score": max(10, _intish(updated.get("score", 0))),
            "selected_harness": harness,
            "selected_skill": _ROUTER_SKILL,
            "threshold": "high",
        }
    )
    return updated


def _omh_status_route_payload(route_payload: dict[str, object]) -> dict[str, object]:
    updated = dict(route_payload)
    harness = primary_harness_for_skill(_ROUTER_SKILL)
    updated.update(
        {
            "action": "dispatch",
            "ambiguous": False,
            "candidate_harness": harness,
            "candidate_skill": _ROUTER_SKILL,
            "confidence": "high",
            "reason": "OMH status or next-action question; show probe-backed status instead of drafting a plan.",
            "recommendations": [
                {
                    "confidence": "high",
                    "evidence_boundary": "Status and roadmap output is local probe evidence only; it is not host plugin load, executor work, review, CI, or merge evidence.",
                    "matched": ["omh_status_question"],
                    "next_action": "show_status",
                    "score": max(10, _intish(updated.get("score", 0))),
                    "skill": _ROUTER_SKILL,
                    "wrapper_guidance": "Render the OMH status and capability roadmap in chat; do not ask for shell approval just to answer status.",
                }
            ],
            "routing_instruction": "Show OMH status and next actions from the local probe roadmap.",
            "routing_prompt_template": "Show OMH status and next actions from the local probe roadmap.\n\nUser message:\n{message}",
            "score": max(10, _intish(updated.get("score", 0))),
            "selected_harness": harness,
            "selected_skill": _ROUTER_SKILL,
            "threshold": "high",
        }
    )
    return updated


def _omh_quickstart_route_payload(route_payload: dict[str, object]) -> dict[str, object]:
    updated = dict(route_payload)
    harness = primary_harness_for_skill(_ROUTER_SKILL)
    updated.update(
        {
            "action": "dispatch",
            "ambiguous": False,
            "candidate_harness": harness,
            "candidate_skill": _ROUTER_SKILL,
            "confidence": "high",
            "reason": "OMH first-use or post-setup question; show the quickstart card instead of drafting a plan.",
            "recommendations": [
                {
                    "confidence": "high",
                    "evidence_boundary": "Quickstart output is local setup and wrapper guidance only; it is not host plugin load, executor work, review, CI, or merge evidence.",
                    "matched": ["omh_quickstart_question"],
                    "next_action": "show_quickstart",
                    "score": max(10, _intish(updated.get("score", 0))),
                    "skill": _ROUTER_SKILL,
                    "wrapper_guidance": "Render the OMH quickstart card in chat; do not ask for shell approval just to answer first-use setup guidance.",
                }
            ],
            "routing_instruction": "Show the OMH quickstart card and first-use Hermes prompts.",
            "routing_prompt_template": "Show the OMH quickstart card and first-use Hermes prompts.\n\nUser message:\n{message}",
            "score": max(10, _intish(updated.get("score", 0))),
            "selected_harness": harness,
            "selected_skill": _ROUTER_SKILL,
            "threshold": "high",
        }
    )
    return updated


def _omh_intro_route_payload(route_payload: dict[str, object]) -> dict[str, object]:
    updated = dict(route_payload)
    harness = primary_harness_for_skill(_ROUTER_SKILL)
    updated.update(
        {
            "action": "dispatch",
            "ambiguous": False,
            "candidate_harness": harness,
            "candidate_skill": _ROUTER_SKILL,
            "confidence": "high",
            "reason": "OMH intro or usage question; show the compact Hermes-facing mental model before the full picker.",
            "recommendations": [
                {
                    "confidence": "high",
                    "evidence_boundary": "Context brief output is routing/help context only; it is not workflow execution, delivery, verification, review, CI, or merge evidence.",
                    "matched": ["omh_intro_question"],
                    "next_action": "show_context_brief",
                    "score": max(10, _intish(updated.get("score", 0))),
                    "skill": _ROUTER_SKILL,
                    "wrapper_guidance": "Render the OMH context brief first, then offer the workflow picker or quickstart card.",
                }
            ],
            "routing_instruction": "Show the OMH context brief and offer the workflow picker as the next action.",
            "routing_prompt_template": "Show the OMH context brief and offer the workflow picker as the next action.\n\nUser message:\n{message}",
            "score": max(10, _intish(updated.get("score", 0))),
            "selected_harness": harness,
            "selected_skill": _ROUTER_SKILL,
            "threshold": "high",
        }
    )
    return updated


def _is_omh_intro_question(message: str) -> bool:
    text = message.strip().lower()
    if not text:
        return False
    omh_markers = ("omh", "oh-my-hermes", "oh my hermes", "오마이헤르메스")
    if not any(marker in text for marker in omh_markers):
        return False
    if any(marker in text for marker in ("status", "doctor", "health", "install", "setup", "next", "상태", "설치", "셋업", "세팅", "다음")):
        return False
    catalog_only_markers = (
        "available",
        "workflow",
        "workflows",
        "skill",
        "skills",
        "workflows available",
        "skills available",
        "commands available",
        "deep-interview",
        "ralplan",
        "ultragoal",
        "loop",
        "ultraprocess",
        "list",
        "menu",
        "picker",
        "명령어",
        "스킬",
        "워크플로",
        "워크플로우",
        "有哪些",
        "可用",
        "使える",
    )
    if any(marker in text for marker in catalog_only_markers):
        return False
    intro_markers = (
        "what is",
        "what are you",
        "how do i use",
        "how should i use",
        "how to use",
        "how does",
        "explain",
        "overview",
        "getting started",
        "mental model",
        "뭐야",
        "무엇이야",
        "어떻게 써",
        "어떻게 사용",
        "사용법",
        "소개",
        "설명",
        "何ですか",
        "使い方",
        "是什么",
        "怎么用",
    )
    return any(marker in text for marker in intro_markers)


def _is_omh_quickstart_question(message: str) -> bool:
    text = message.strip().lower()
    if not text:
        return False
    omh_markers = ("omh", "oh-my-hermes", "oh my hermes", "오마이헤르메스")
    if not any(marker in text for marker in omh_markers):
        return False
    quickstart_markers = (
        "quickstart",
        "getting started",
        "first use",
        "what next",
        "what should i do next",
        "what do i do next",
        "next action",
        "after setup",
        "after install",
        "installed correctly",
        "setup next",
        "next step",
        "처음",
        "퀵스타트",
        "다음 액션",
        "다음 단계",
        "이제 뭐",
        "설치됐",
        "설치 되었",
        "설치 완료",
        "셋업",
        "세팅",
    )
    return any(marker in text for marker in quickstart_markers)


def _is_omh_status_question(message: str) -> bool:
    text = message.strip().lower()
    if not text:
        return False
    omh_markers = ("omh", "oh-my-hermes", "oh my hermes", "오마이헤르메스")
    if not any(marker in text for marker in omh_markers):
        return False
    catalog_markers = (
        "what can",
        "what does",
        "available",
        "workflows",
        "skills",
        "commands",
        "뭐 할",
        "뭘 도와",
        "명령어",
        "스킬",
        "워크플로",
    )
    if any(marker in text for marker in catalog_markers) and not any(
        marker in text
        for marker in ("status", "health", "doctor", "setup", "install", "installed", "next", "상태", "다음", "설치", "셋업", "세팅", "정상", "진단")
    ):
        return False
    status_markers = (
        "status",
        "health",
        "doctor",
        "diagnose",
        "installed",
        "installation",
        "setup",
        "set up",
        "next action",
        "what next",
        "what should i do next",
        "what do i do next",
        "상태",
        "다음",
        "액션",
        "설치",
        "셋업",
        "세팅",
        "정상",
        "확인",
        "헬스",
        "진단",
    )
    return any(marker in text for marker in status_markers)


def _roadmap_next_actions(roadmap: dict[str, Any], *, limit: int) -> list[dict[str, object]]:
    actions = roadmap.get("next_actions", [])
    if not isinstance(actions, list):
        return []
    compact: list[dict[str, object]] = []
    for action in actions:
        if not isinstance(action, dict):
            continue
        item = {
            "id": str(action.get("id", "")),
            "kind": str(action.get("kind", "")),
            "label": str(action.get("label", "")),
            "why": str(action.get("why", "")),
            "boundary": str(action.get("boundary", "")),
            "capabilities": _as_string_list(action.get("capabilities", [])),
        }
        command = str(action.get("command", "")).strip()
        operator_instruction = str(action.get("operator_instruction", "")).strip()
        if command:
            item["command"] = command
        if operator_instruction:
            item["operator_instruction"] = operator_instruction
        compact.append(item)
        if len(compact) >= limit:
            break
    return compact


def _roadmap_next_action_sentence(actions: list[dict[str, object]]) -> str:
    if not actions:
        return "Next: no blocking OMH setup action is currently required."
    first = actions[0]
    label = str(first.get("label", "Check OMH status")).strip() or "Check OMH status"
    kind = str(first.get("kind", "")).strip()
    command = str(first.get("command", "")).strip()
    operator_instruction = str(first.get("operator_instruction", "")).strip()
    why = str(first.get("why", "")).strip()
    if command and kind == "product_gap" and "<" not in command:
        return f"Next: {label} with `{command}`."
    if operator_instruction:
        return f"Next: {label}: {operator_instruction}"
    if why:
        return f"Next: {label}. {why}"
    return f"Next: {label}."


def _section_item_without_next_prefix(value: str) -> str:
    text = value.strip()
    if text.lower().startswith("next:"):
        return text.split(":", 1)[1].strip()
    return text


def _intish(value: object, default: int = 0) -> int:
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
    suggestions = _as_dict_list(preview.get("suggestions", []))
    insert_text = str(suggestions[0].get("insert_text", "./omh")) if suggestions else "./omh"
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
                    "suggestions": suggestions,
                },
            ),
            _action(
                "show_skill_picker",
                "Open picker",
                "secondary",
                payload={
                    "insert_text": insert_text,
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
    catalog_question = _is_skill_catalog_question(message)
    primer = _context_primer_state()
    extra_state = {
        "route_action": decision.get("action", "dispatch"),
        "confidence": decision.get("confidence", "low"),
        "selected_workflow": _ROUTER_SKILL,
        "catalog_question": catalog_question,
        "context_primer": primer,
        "skill_picker": picker,
        "direct_invocation_aliases": ["./omh", "/omh", "./skills", "/skills"],
    }
    if catalog_question:
        extra_state["capability_summary"] = _catalog_capability_summary()
    return _chat_response(
        kind="skill_picker",
        headline="Here are the OMH workflows." if catalog_question else "Choose an OMH workflow.",
        body=_skill_picker_body(catalog_question=catalog_question),
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
                    "featured_options": picker["featured_options"],
                    "groups": picker["groups"],
                },
            ),
            _action("search_skills", "Search workflows", "secondary", payload={"input_schema": {"query": "string"}}),
            _action("show_status", "Show status", "secondary"),
        ],
        claim_boundary="Choosing a skill is routing intent only; it is not plan acceptance, dispatch, execution, review, CI, or verification evidence.",
        extra_state=extra_state,
    )


def _skill_picker_body(*, catalog_question: bool) -> str:
    if catalog_question:
        return "\n".join(
            [
                "You do not need to run a shell command for this. OMH covers planning, ops, deliverables, coding handoffs, loops, and status.",
                "",
                "Start here:",
                "- Route for me: let Hermes choose the safest workflow from your message.",
                "- Choose workflow: pick from the grouped OMH workflow lanes.",
                "- Search workflows: find the exact skill when you already know the job.",
                "",
                "Common lanes:",
                "- Intent to plan: deep-interview, ralplan, ultragoal, loop, ultraprocess.",
                "- Company/product ops: feedback-triage, research-brief, strategy-brief, research-department, paper-learning.",
                "- Deliverables/visuals: materials-package, report-package, img-summary.",
                "- Coding/runtime: request-to-handoff, idea-to-deploy, code-review, executor selection.",
            ]
        )
    return "\n".join(
        [
            "Pick how to start, or choose Route for me and Hermes will select the safest next step from the request.",
            "",
            "Best default:",
            "- Route for me: paste the request and let Hermes choose the workflow.",
            "",
            "Manual lanes:",
            "- Plan or loop: deep-interview, ralplan, ultragoal, loop, ultraprocess.",
            "- Ops or research: feedback-triage, research-brief, paper-learning, strategy-brief.",
            "- Deliverables or visuals: materials-package, report-package, img-summary.",
            "- Coding: request-to-handoff, idea-to-deploy, code-review, executor selection.",
        ]
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
    featured_options = [
        _compact_picker_option(option)
        for option in options
        if option["id"] == _ROUTER_SKILL
    ]
    groups = _skill_picker_groups(options)
    return {
        "schema_version": SKILL_PICKER_SCHEMA_VERSION,
        "trigger": _first_token(message),
        "source": source,
        "selection_mode": "single_select",
        "options": options,
        "featured_options": featured_options,
        "groups": groups,
        "rendering_hints": {
            "discord": "Render Route for me first, then grouped sections; keep the full options list only as a compatibility fallback.",
            "slack": "Render Route for me first, then grouped sections or a grouped static select in the current thread.",
            "hermes_tui": "Render grouped sections with short direct invocations; keep real skill names unchanged.",
        },
        "recommended_rendering": "Show the featured Route for me option first, then the groups. Use search_skills for the full installed catalog.",
        "claim_boundary": "This picker records routing intent only; selected workflows still need their own plan, handoff, or observed evidence.",
    }


def _skill_picker_groups(options: list[dict[str, object]]) -> list[dict[str, object]]:
    by_id = {str(option["id"]): option for option in options}
    groups = []
    for group in _CONTEXT_PRIMER_GROUPS:
        group_options = [
            _compact_picker_option(by_id[workflow_id])
            for workflow_id in group["workflows"]
            if workflow_id in by_id and workflow_id != _ROUTER_SKILL
        ]
        if not group_options:
            continue
        groups.append(
            {
                "id": group["id"],
                "label": group["label"],
                "use_when": group["use_when"],
                "option_ids": [str(option["id"]) for option in group_options],
                "options": group_options,
                "action_id": "choose_skill",
            }
        )
    return groups


def _compact_picker_option(option: dict[str, object]) -> dict[str, object]:
    return {
        "id": str(option.get("id", "")),
        "label": str(option.get("label", "")),
        "description": str(option.get("description", "")),
        "direct_invocation": str(option.get("direct_invocation", "")),
        "harness": str(option.get("harness", "")),
        "action_id": str(option.get("action_id", "choose_skill")),
    }


def _context_primer_state() -> dict[str, object]:
    installed = {definition.name for definition in installable_skill_definitions()}
    groups = []
    for group in _CONTEXT_PRIMER_GROUPS:
        workflows = tuple(workflow for workflow in group["workflows"] if workflow in installed)
        if not workflows:
            continue
        groups.append(
            {
                "id": group["id"],
                "label": group["label"],
                "workflows": workflows,
                "use_when": group["use_when"],
            }
        )
    return {
        "schema_version": CONTEXT_PRIMER_SCHEMA_VERSION,
        "summary": (
            "OMH is a Hermes workflow layer. It helps Hermes route natural-language work into skills, plans, "
            "deliverables, coding handoffs, loops, and status updates without treating prepared guidance as observed work."
        ),
        "workflow_groups": groups,
        "workflow_context_cards": workflow_context_cards(),
        "routing_rule": "Use Route for me when the user did not choose a workflow; use explicit workflow names when the user did.",
        "evidence_rule": "Prepared plans, prompts, cards, or handoffs are not execution, file generation, delivery, review, CI, merge, or verification evidence.",
        "inventory_rule": "Render the picker for common choices and use search_skills for the full installed catalog.",
    }


def _catalog_capability_summary() -> dict[str, object]:
    from ..capabilities.registry import capability_summary

    summary = capability_summary()
    compact_lanes = []
    for lane in _as_dict_list(summary.get("lanes", [])):
        compact_lanes.append(
            {
                "id": lane.get("id", ""),
                "label": lane.get("label", ""),
                "owner_role": lane.get("owner_role", ""),
                "use_for": lane.get("use_for", ""),
                "primary_skills": _as_string_list(lane.get("primary_skills", [])),
                "representative_playbooks": [
                    {
                        "id": playbook.get("id", ""),
                        "summary": playbook.get("summary", ""),
                        "owner_role": playbook.get("owner_role", ""),
                        "first_stage": playbook.get("first_stage", {}),
                    }
                    for playbook in _as_dict_list(lane.get("representative_playbooks", []))[:3]
                ],
                "wrapper_actions": _as_string_list(lane.get("wrapper_actions", []))[:6],
                "examples": _as_string_list(lane.get("examples", []))[:3],
            }
        )
    return {
        "schema_version": summary.get("schema_version", "omh_capability_summary/v1"),
        "purpose": summary.get("purpose", ""),
        "lanes": compact_lanes,
        "workflow_context_cards": _as_dict_list(summary.get("workflow_context_cards", [])),
        "direct_response_guidance": _as_string_list(summary.get("direct_response_guidance", [])),
        "evidence_boundary": _as_string_list(summary.get("evidence_boundary", [])),
    }


def _as_dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _as_string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    if isinstance(value, tuple):
        return [str(item) for item in value if str(item)]
    if isinstance(value, str) and value:
        return [value]
    return []


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
    if "workflow_explanation" not in state:
        state["workflow_explanation"] = workflow_explanation_payload(
            kind=kind,
            phase=phase,
            next_action=next_action,
            state=state,
            claim_boundary=claim_boundary,
        )
    usage_trace = usage_trace_payload(kind=kind, phase=phase, next_action=next_action, state=state)
    headline_with_prefix = headline_with_usage_prefix(headline, str(usage_trace["visible_prefix"]))
    response: dict[str, object] = {
        "schema_version": CHAT_RESPONSE_SCHEMA_VERSION,
        "kind": kind,
        "visibility": "thread",
        "headline": headline_with_prefix,
        "plain_headline": headline,
        "body": body,
        "state": state,
        "usage_trace": usage_trace,
        "messenger_rendering": messenger_rendering_contract(
            visible_prefix=str(usage_trace["visible_prefix"]),
            first_line=headline_with_prefix,
            body=body,
            claim_boundary=claim_boundary,
        ),
        "actions": actions,
        "claim_boundary": claim_boundary,
    }
    if status_card:
        response["status_card"] = status_card
    return response


def workflow_explanation_payload(
    *,
    kind: str,
    phase: str,
    next_action: str,
    state: dict[str, object],
    claim_boundary: str,
) -> dict[str, object]:
    workflow = _usage_workflow(state)
    label = workflow or _usage_label(state, kind=kind, phase=phase, next_action=next_action)
    harness = primary_harness_for_skill(workflow) if workflow else ""
    payload: dict[str, object] = {
        "schema_version": WORKFLOW_EXPLANATION_SCHEMA_VERSION,
        "selected_workflow": workflow,
        "label": label,
        "selected_harness": harness,
        "why_this_workflow": _workflow_explanation_reason(state, workflow=workflow, label=label),
        "next_action": next_action,
        "next_action_label": next_action.replace("_", " "),
        "not_evidence_yet": _workflow_explanation_not_evidence(state, claim_boundary=claim_boundary),
        "claim_boundary": claim_boundary,
        "rendering_hint": "Show this as a compact why/next/not-evidence card in chat surfaces.",
    }
    context_card = workflow_context_card_for_workflow(workflow)
    if context_card:
        payload["workflow_context_card"] = context_card
        payload["workflow_context_id"] = context_card["id"]
    return payload


def _workflow_explanation_reason(state: dict[str, object], *, workflow: str, label: str) -> str:
    explanation_reason = str(state.get("workflow_explanation_reason") or "").strip()
    if explanation_reason:
        return explanation_reason
    reason = str(state.get("routing_reason") or "").strip()
    if reason:
        return reason
    if workflow:
        return f"Selected `{workflow}` from the message, workflow metadata, and guardrail policy."
    return f"Using the `{label}` response state for this step."


def _workflow_explanation_not_evidence(state: dict[str, object], *, claim_boundary: str) -> list[str]:
    explicit = state.get("evidence_not_observed")
    if isinstance(explicit, list) and explicit:
        return [str(item) for item in explicit if str(item)]
    text = claim_boundary.lower()
    items: list[str] = []
    for marker, label in (
        ("plan acceptance", "plan acceptance"),
        ("dispatch", "executor/runtime dispatch"),
        ("execution", "execution"),
        ("implementation", "implementation"),
        ("image", "image generation"),
        ("file", "file generation/export"),
        ("delivery", "delivery"),
        ("review", "review"),
        ("ci", "CI"),
        ("merge", "merge"),
        ("verification", "verification"),
    ):
        if marker in text and label not in items:
            items.append(label)
    if items:
        return items
    if "prepared" in text:
        return ["execution", "verification", "delivery"]
    return ["completion claim without observed evidence"]


def usage_trace_payload(*, kind: str, phase: str, next_action: str, state: dict[str, object]) -> dict[str, object]:
    workflow = _usage_workflow(state)
    harness = primary_harness_for_skill(workflow) if workflow else ""
    label = workflow or _usage_label(state, kind=kind, phase=phase, next_action=next_action)
    trace: dict[str, object] = {
        "schema_version": USAGE_TRACE_SCHEMA_VERSION,
        "brand": "omh",
        "visibility": "visible_prefix",
        "visible_prefix": f"[omh] {label}",
        "label": label,
        "selected_workflow": workflow,
        "selected_harness": harness,
        "phase": phase,
        "next_action": next_action,
        "evidence_state": _usage_evidence_state(state, phase=phase, next_action=next_action),
        "claim_boundary": "This trace is a routing/status marker, not execution evidence.",
    }
    executor = str(state.get("selected_executor_profile") or state.get("executor_target") or "")
    if executor:
        trace["selected_executor_profile"] = executor
    runtime_family = str(state.get("runtime_family") or "")
    if runtime_family:
        trace["runtime_family"] = runtime_family
    context_card = workflow_context_card_for_workflow(workflow)
    if context_card:
        trace["workflow_context_id"] = context_card["id"]
    return trace


def _usage_workflow(state: dict[str, object]) -> str:
    for key in ("selected_workflow", "recommended_workflow"):
        value = str(state.get(key, "") or "").strip()
        if value:
            return value
    return ""


def _usage_label(state: dict[str, object], *, kind: str, phase: str, next_action: str) -> str:
    executor = str(state.get("selected_executor_profile") or state.get("executor_target") or "").strip()
    if executor:
        return f"{executor}-handoff"
    if kind == "plan":
        return "plan"
    if kind == "clarification":
        return "clarification"
    if kind == "quickstart":
        return "quickstart"
    if kind == "context_brief":
        return "context"
    if kind in {"status", "blocker"}:
        return "status"
    if kind == "handoff":
        return "handoff"
    if kind == "command_preview":
        return "command-preview"
    if kind == "skill_picker":
        return _ROUTER_SKILL
    return phase or next_action or kind or "workflow"


def _usage_evidence_state(state: dict[str, object], *, phase: str, next_action: str) -> str:
    if next_action in {"wait_for_executor_evidence", "record_review_evidence", "record_verification_evidence", "record_ci_evidence", "record_merge_readiness"}:
        return "observed_partial"
    if next_action.startswith("surface_") and next_action.endswith("_blocker"):
        return "observed_partial"
    if next_action in {"report_completion_with_evidence", "report_merge_ready", "report_merged"}:
        return "observed_reportable"
    if phase.endswith("prepared") or "handoff" in phase or next_action in {"dispatch_to_workflow", "present_plan", "accept_or_revise_plan"}:
        return "prepared_not_observed"
    if bool(state.get("execution_observed", False)) or bool(state.get("verification_observed", False)):
        return "observed_partial"
    return "routing_not_execution"


def headline_with_usage_prefix(headline: str, visible_prefix: str) -> str:
    if headline.startswith("[omh] "):
        return headline
    return f"{visible_prefix} - {headline}"


def messenger_rendering_contract(
    *,
    visible_prefix: str,
    first_line: str,
    body: str,
    claim_boundary: str,
    render_profile: str = RENDER_PROFILE_LIMITED_MARKDOWN,
) -> dict[str, object]:
    resolved_profile = _normalize_render_profile(render_profile)
    safe_body_text, safe_transforms = _messenger_safe_body(body)
    if resolved_profile == RENDER_PROFILE_RICH_MARKDOWN:
        body_text = body
        body_format = "rich_markdown"
        preferred_blocks = ["short_paragraph", "bulleted_list", "numbered_list", "markdown_table", "status_lines"]
        avoid_blocks = ["large_unbroken_block"]
        table_policy = "preserve_markdown_tables_when_supported"
        transforms: list[str] = []
    else:
        body_text = safe_body_text
        body_format = "messenger_safe_markdown"
        preferred_blocks = ["short_paragraph", "bulleted_list", "numbered_list", "status_lines"]
        avoid_blocks = ["markdown_table", "wide_table", "large_unbroken_block"]
        table_policy = "convert_tables_to_bullets_for_messenger"
        transforms = safe_transforms
    return {
        "schema_version": MESSENGER_RENDERING_SCHEMA_VERSION,
        "render_profile": resolved_profile,
        "visible_prefix": visible_prefix,
        "first_line": first_line,
        "body_format": body_format,
        "body_text": body_text,
        "body_blocks": _render_body_blocks(body_text, render_profile=resolved_profile),
        "fallback_body_format": "messenger_safe_markdown",
        "fallback_body_text": safe_body_text,
        "fallback_body_blocks": _messenger_body_blocks(safe_body_text),
        "preferred_blocks": preferred_blocks,
        "avoid_blocks": avoid_blocks,
        "chunking": {
            "max_recommended_chars": 1800,
            "split_on": ["headings", "bullets", "paragraphs"],
        },
        "transforms_applied": transforms,
        "fallback_transforms_applied": safe_transforms,
        "prefix_policy": {
            "default": "once_per_response_first_line",
            "repeat_when": "adapter_splits_response_across_separate_messages_or_chunks",
            "do_not_repeat": "every_paragraph_or_every_line",
        },
        "platform_hints": {
            "discord": "Start the first message with the visible prefix, prefer bullets or numbered lists over tables, and repeat the prefix only if the adapter splits a long response into separate messages.",
            "slack": "Start the response with the visible prefix, prefer blocks or bullets over wide Markdown tables, and keep claim boundaries visible.",
            "telegram": "Start the response with the visible prefix, keep sections short, and avoid table layouts.",
            "hermes": "Render body_text as rich Markdown when the Hermes surface supports it; use fallback_body_text when relaying to a narrow chat adapter.",
            "generic": "Use body_text for the declared render_profile; use fallback_body_text if the actual surface cannot render Markdown tables.",
        },
        "table_policy": table_policy,
        "body_preview": _short_text(body_text, limit=180),
        "claim_boundary": claim_boundary,
    }


def render_profile_for_source(source: str, source_metadata: dict[str, object] | None = None) -> str:
    metadata = source_metadata or {}
    explicit = str(metadata.get("render_profile", "")).strip()
    if explicit in RENDER_PROFILES:
        return explicit
    if source in _LIMITED_MARKDOWN_SOURCES:
        return RENDER_PROFILE_LIMITED_MARKDOWN
    return RENDER_PROFILE_RICH_MARKDOWN


def _normalize_render_profile(render_profile: str) -> str:
    if render_profile in RENDER_PROFILES:
        return render_profile
    return RENDER_PROFILE_LIMITED_MARKDOWN


def _render_body_blocks(body: str, *, render_profile: str) -> list[dict[str, object]]:
    if render_profile == RENDER_PROFILE_RICH_MARKDOWN:
        return _rich_markdown_body_blocks(body)
    return _messenger_body_blocks(body)


def _messenger_safe_body(body: str) -> tuple[str, list[str]]:
    lines = body.splitlines()
    if not lines:
        return body, []
    output: list[str] = []
    transforms: list[str] = []
    index = 0
    in_code_fence = False
    while index < len(lines):
        if _is_code_fence_line(lines[index]):
            in_code_fence = not in_code_fence
            output.append(lines[index])
            index += 1
            continue
        if in_code_fence:
            output.append(lines[index])
            index += 1
            continue
        if not _is_markdown_table_start(lines, index):
            output.append(lines[index])
            index += 1
            continue
        block: list[str] = []
        while index < len(lines) and _is_markdown_table_line(lines[index]):
            block.append(lines[index])
            index += 1
        converted = _markdown_table_to_bullets(block)
        if not converted:
            output.extend(block)
            continue
        if output and output[-1].strip():
            output.append("")
        output.extend(converted)
        transforms.append("markdown_table_to_bullets")
    return "\n".join(output), sorted(set(transforms))


def _is_code_fence_line(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("```") or stripped.startswith("~~~")


def _is_markdown_table_start(lines: list[str], index: int) -> bool:
    if index + 1 >= len(lines):
        return False
    return _is_markdown_table_line(lines[index]) and _is_markdown_separator_line(lines[index + 1])


def _is_markdown_table_line(line: str) -> bool:
    stripped = line.strip()
    return "|" in stripped and len(_split_markdown_table_row(stripped)) >= 2


def _is_markdown_separator_line(line: str) -> bool:
    cells = _split_markdown_table_row(line)
    if not cells:
        return False
    for cell in cells:
        marker = cell.replace(":", "").replace("-", "").strip()
        if marker:
            return False
        if cell.count("-") < 3:
            return False
    return True


def _markdown_table_to_bullets(lines: list[str]) -> list[str]:
    if len(lines) < 3 or not _is_markdown_separator_line(lines[1]):
        return []
    headers = _split_markdown_table_row(lines[0])
    if not headers:
        return []
    bullets: list[str] = []
    for row in lines[2:]:
        if _is_markdown_separator_line(row):
            continue
        cells = _split_markdown_table_row(row)
        if not any(cells):
            continue
        while len(cells) < len(headers):
            cells.append("")
        first = cells[0].strip()
        details = [
            f"{header}: {cell}"
            for header, cell in zip(headers[1:], cells[1:])
            if header.strip() and cell.strip()
        ]
        if first and details:
            bullets.append(f"- {first}: {'; '.join(details)}")
        elif first:
            bullets.append(f"- {headers[0]}: {first}")
        elif details:
            bullets.append(f"- {'; '.join(details)}")
    return bullets


def _split_markdown_table_row(line: str) -> list[str]:
    stripped = line.strip()
    cells: list[str] = []
    current: list[str] = []
    code_tick_length = 0
    index = 0
    while index < len(stripped):
        character = stripped[index]
        if character == "`" and not _is_escaped(stripped, index):
            run_end = index
            while run_end < len(stripped) and stripped[run_end] == "`":
                run_end += 1
            run_length = run_end - index
            if code_tick_length == 0:
                code_tick_length = run_length
            elif code_tick_length == run_length:
                code_tick_length = 0
            current.append(stripped[index:run_end])
            index = run_end
            continue
        if character == "|" and code_tick_length == 0 and not _is_escaped(stripped, index):
            cells.append(_normalize_table_cell("".join(current)))
            current = []
            index += 1
            continue
        current.append(character)
        index += 1
    cells.append(_normalize_table_cell("".join(current)))
    if cells and not cells[0]:
        cells = cells[1:]
    if cells and not cells[-1]:
        cells = cells[:-1]
    return cells


def _is_escaped(value: str, index: int) -> bool:
    slash_count = 0
    cursor = index - 1
    while cursor >= 0 and value[cursor] == "\\":
        slash_count += 1
        cursor -= 1
    return slash_count % 2 == 1


def _normalize_table_cell(value: str) -> str:
    return _unescape_table_pipes(value.strip())


def _unescape_table_pipes(value: str) -> str:
    output: list[str] = []
    index = 0
    while index < len(value):
        if value[index] == "\\" and index + 1 < len(value) and value[index + 1] == "|":
            output.append("|")
            index += 2
            continue
        output.append(value[index])
        index += 1
    return "".join(output)


def _messenger_body_blocks(body: str) -> list[dict[str, object]]:
    blocks: list[dict[str, object]] = []
    current: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                blocks.append({"type": "paragraph", "text": " ".join(current)})
                current = []
            continue
        if stripped.startswith(("- ", "* ")):
            if current:
                blocks.append({"type": "paragraph", "text": " ".join(current)})
                current = []
            blocks.append({"type": "bullet", "text": stripped[2:].strip()})
            continue
        numbered_text = _numbered_list_text(stripped)
        if numbered_text:
            if current:
                blocks.append({"type": "paragraph", "text": " ".join(current)})
                current = []
            blocks.append({"type": "numbered", "text": numbered_text})
            continue
        current.append(stripped)
    if current:
        blocks.append({"type": "paragraph", "text": " ".join(current)})
    return blocks


def _rich_markdown_body_blocks(body: str) -> list[dict[str, object]]:
    lines = body.splitlines()
    if not lines:
        return []
    blocks: list[dict[str, object]] = []
    paragraph: list[str] = []
    index = 0
    in_code_fence = False
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if _is_code_fence_line(line):
            in_code_fence = not in_code_fence
            paragraph.append(stripped)
            index += 1
            continue
        if not in_code_fence and _is_markdown_table_start(lines, index):
            if paragraph:
                blocks.extend(_messenger_body_blocks("\n".join(paragraph)))
                paragraph = []
            table_lines: list[str] = []
            while index < len(lines) and _is_markdown_table_line(lines[index]):
                table_lines.append(lines[index])
                index += 1
            block = _markdown_table_block(table_lines)
            if block:
                blocks.append(block)
            else:
                paragraph.extend(table_lines)
            continue
        if not stripped:
            if paragraph:
                blocks.extend(_messenger_body_blocks("\n".join(paragraph)))
                paragraph = []
            index += 1
            continue
        paragraph.append(stripped)
        index += 1
    if paragraph:
        blocks.extend(_messenger_body_blocks("\n".join(paragraph)))
    return blocks


def _markdown_table_block(lines: list[str]) -> dict[str, object]:
    if len(lines) < 2 or not _is_markdown_separator_line(lines[1]):
        return {}
    headers = _split_markdown_table_row(lines[0])
    rows = [
        _split_markdown_table_row(row)
        for row in lines[2:]
        if not _is_markdown_separator_line(row) and any(_split_markdown_table_row(row))
    ]
    return {
        "type": "markdown_table",
        "markdown": "\n".join(lines),
        "headers": headers,
        "rows": rows,
    }


def _numbered_list_text(stripped: str) -> str:
    marker = ""
    for index, character in enumerate(stripped):
        if character.isdigit():
            continue
        if character in {".", ")"} and index > 0:
            marker = stripped[: index + 1]
        break
    if not marker:
        return ""
    if len(stripped) <= len(marker) or not stripped[len(marker)].isspace():
        return ""
    rest = stripped[len(marker) :].strip()
    return rest


def _short_text(value: str, *, limit: int) -> str:
    text = " ".join(value.split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _action(action_id: str, label: str, style: str, *, enabled: bool = True, payload: dict[str, object] | None = None) -> dict[str, object]:
    if action_id not in VISIBLE_ACTIONS and not action_id.startswith("answer:"):
        raise ValueError(f"unsupported chat response action: {action_id}")
    return {"id": action_id, "label": label, "style": style, "enabled": enabled, "payload": payload or {}}


def _action_from_spec(spec: dict[str, object]) -> dict[str, object]:
    payload_value = spec.get("payload")
    payload = {str(key): value for key, value in payload_value.items()} if isinstance(payload_value, dict) else None
    return _action(
        str(spec.get("id", "")),
        str(spec.get("label", "")),
        str(spec.get("style", "")),
        enabled=bool(spec.get("enabled", True)),
        payload=payload,
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
