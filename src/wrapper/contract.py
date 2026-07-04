from __future__ import annotations

from functools import lru_cache
import hashlib
from pathlib import Path
from typing import Any

from ..context_safety import compact_progress_events
from ..coding.agentic_playbook import maybe_build_agentic_playbook
from ..coding.agentic_playbook_contract import chat_response_with_agentic_playbook
from ..ingress import CHAT_SOURCES, compact_source_metadata, extract_message_text, extract_source_metadata
from ..routing.catalog_questions import is_skill_catalog_question as _is_skill_catalog_question
from ..routing.chat import public_chat_route_payload, route_explanation_payload
from ..routing.missed_route import is_missed_route_feedback
from ..routing.omh_help import (
    is_omh_intro_question as _is_omh_intro_question,
    is_omh_quickstart_question as _is_omh_quickstart_question,
    is_omh_status_question as _is_omh_status_question,
)
from ..coding_delegation import CODING_EXECUTOR_TARGETS, build_coding_delegation_payload
from ..capabilities.families import capability_family_cards
from ..context import build_context_brief
from ..executors import executor_label
from ..goal_loop import build_loop_start_card
from ..hermes_planning import build_hermes_plan_payload, is_coding_shaped_task
from ..learning_candidate import build_learning_candidate_card
from ..memory import memory_recall_pack_for_handoff
from ..operator_productivity import build_agent_operator_productivity_card
from ..paths import OmhPaths, resolve_paths
from ..plugin_bundle.omh.awareness import workflow_context_card_for_workflow, workflow_context_cards
from ..probe import probe_capabilities
from ..quickstart import build_quickstart_card
from ..skills.catalog import installable_skill_definitions, primary_harness_for_skill, retained_delegation_skill_names
from ..setup_profiles import read_setup_profile
from ..surfaces.evidence_copy import not_evidence_action_suffix, not_evidence_reply_suffix
from ..visual_summary import image_generation_setup_fallback
from .hermes_runtime import (
    hermes_coding_team_body,
    hermes_coding_team_claim_boundary,
    hermes_coding_team_extra_action_specs,
)
from .localized_copy import (
    chat_copy,
    detect_copy_locale,
    is_localized_locale,
    skill_picker_body as localized_skill_picker_body,
    skill_picker_headline,
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
    "show_coding_handoff_status",
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
    "prepare_source_finder_plan",
    "show_source_candidates",
    "record_source_candidate",
    "record_source_link_observed",
    "record_download_observed",
    "record_file_hash",
    "record_text_extraction_observed",
    "record_license_check",
    "choose_source",
    "route_to_downstream_workflow",
    "show_acquisition_status",
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
    "prepare_design_quality_gate",
    "show_design_quality_gate",
    "record_design_reference",
    "record_content_qa",
    "record_layout_qa",
    "record_surface_quality_matrix",
    "prepare_frontend_handoff",
    "show_frontend_handoff",
    "record_browser_capture",
    "record_accessibility_check",
    "record_performance_check",
    "prepare_visual_qa",
    "show_visual_qa",
    "record_render_capture",
    "record_visual_diff",
    "record_visual_oracle_review",
    "record_cjk_layout_findings",
    "record_visual_qa_verdict",
    "dispatch_to_workflow",
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
    "prepare_quality_performance_and_usability_review",
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
    "show_learning_candidate",
    "copy_learn_prompt",
    "add_regression_case",
    "audit_learning_readiness",
    "export_learning_bundle",
    "replay_regression_cases",
    "check_learning_index",
    "rebuild_learning_index",
    "run_omh_update",
    "run_omh_setup",
    "run_omh_doctor",
    "run_omh_uninstall",
    "run_omh_install",
    "run_omh_list",
    "cancel",
)
_ROUTE_TO_MODE = {"dispatch": "plan", "clarify": "clarify", "fallback": "clarify"}
_CLARIFICATION_SKILLS = {"deep-interview"}
_ROUTER_SKILL = "oh-my-hermes"
_SKILL_PICKER_TOKENS = frozenset({"omh", "ohmy", "skills"})
_SKILL_PICKER_HELP_TOKENS = frozenset({"", "help", "menu", "list", "commands", "workflows", "skills"})
_COMMAND_PREVIEW_PREFIXES = ("./", "/")
_COMMAND_PREVIEW_ALIAS = "omh"
_MESSAGE_EXECUTOR_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("claude-code", ("claude code", "claude-code", "claudecode", "클로드 코드", "클로드코드")),
    ("codex", ("codex", "코덱스")),
    ("omc-runtime", ("omc", "oh my claude", "oh-my-claude", "oh my claude code", "oh-my-claude-code")),
    ("omo-runtime", ("omo", "oh my openagent", "oh-my-openagent", "openagent runtime")),
    ("omx-runtime", ("omx", "oh my codex", "oh-my-" + "codex", "omx runtime")),
    (
        "hermes",
        (
            "hermes coding",
            "hermes runtime",
            "hermes itself",
            "with hermes",
            "hermes만으로",
            "hermes 만으로",
            "헤르메스가 코딩",
            "헤르메스로 구현",
            "헤르메스 자체",
            "헤르메스 런타임",
            "헤르메스만으로",
            "헤르메스 만으로",
        ),
    ),
)
_SKILL_PICKER_ENTRIES = (
    ("oh-my-hermes", "Route for me", "Let Hermes choose the safest workflow.", "./omh <request>"),
    ("deep-interview", "Deep Interview", "Clarify fuzzy goals before planning.", "./deep-interview <request>"),
    ("ralplan", "Ralplan", "Research and plan before execution.", "./ralplan <request>"),
    ("loop", "Loop", "Iterate on a loopable long-horizon goal.", "./loop <goal>"),
    ("ultraprocess", "Ultra Process", "Run one research-plan-implement-review-sync cycle.", "./ultraprocess <request>"),
    ("feedback-triage", "Feedback Triage", "Turn customer or product signals into investigation.", "./feedback-triage <signal>"),
    ("web-research", "Web Research", "Gather source-backed current evidence.", "./web-research <question>"),
    ("source-finder", "Source Finder", "Prepare typed source candidates before downstream work.", "./source-finder <target>"),
    ("research-department", "Research Department", "Prepare Scout, Analyst, and Briefer research ops.", "./research-department <topic>"),
    ("paper-learning", "Paper Learning", "Explain a paper by level without dropping coverage.", "./paper-learning <paper>"),
    ("agent-ops-review", "Agent Ops Review", "See quality, blockers, next action, and throughput levers.", "./agent-ops-review <request>"),
    ("code-review", "Code Review", "Review completed work without overclaiming evidence.", "./code-review <scope>"),
    ("materials-package", "Materials Package", "Shape PPT, PDF, spreadsheet, document, or Markdown deliverables.", "./materials-package <brief>"),
    ("img-summary", "Img Summary", "Prepare image-generation-ready summary cards.", "./img-summary <source>"),
    ("design-quality-gate", "Design Quality Gate", "Raise visual, content, layout, and publishing quality.", "./design-quality-gate <brief>"),
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
        "workflows": ("feedback-triage", "research-department", "source-finder", "paper-learning", "web-research", "strategy-brief", "automation-blueprint"),
        "use_when": "The user needs customer-signal triage, source-backed research, recurring ops, meeting/report work, or strategy synthesis.",
    },
    {
        "id": "deliverables_and_visuals",
        "label": "Deliverables and visuals",
        "workflows": ("design-quality-gate", "frontend", "visual-qa", "materials-package", "deliverable-package", "img-summary", "report-package"),
        "use_when": "The user wants files, decks, PDFs, frontend surfaces, screenshots, posters, reports, image-summary cards, premium design QA, or attachment-ready delivery states.",
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
    "source-finder",
    "doctor",
    "skill",
    "wiki",
    *_RETAINED_DELEGATION_SKILLS,
} - (_CLARIFICATION_SKILLS | {"cancel"})
_CODING_OWNER_NEXT_ACTIONS = frozenset(
    {
        "prepare_coding_handoff",
        "prepare_coding_runtime_handoff",
        "start_ultraprocess",
    }
)
_CODING_OWNER_WORKFLOWS = frozenset(
    {
        "ultraprocess",
        "ultrawork",
        "ultragoal",
        "ralph",
        "ai-slop-cleaner",
        "team",
    }
)
_CODING_OWNER_WHEN_CODE_SHAPED = frozenset({"code-review"})
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
    "choose_executor": (
        "handoff",
        "Choose who should own the coding work.",
        "A coding handoff path is not selected yet; no executor/runtime dispatch is observed.",
        "Executor choice is not dispatch or implementation evidence.",
    ),
    "dispatch_to_executor": (
        "handoff",
        "An executor handoff is ready.",
        "I have prepared the handoff, but executor/runtime dispatch is not observed yet.",
        "Preparation is not execution evidence.",
    ),
    "show_prompt_handoff": (
        "handoff",
        "A prompt handoff is ready.",
        "The selected prompt handoff is prepared, but OMH has not dispatched it to an executor.",
        "Prompt handoff is prepared only; OMH has not dispatched it to an executor.",
    ),
    "show_runtime_handoff": (
        "handoff",
        "A runtime handoff is ready.",
        "The selected runtime handoff is prepared, but runtime start is not observed yet.",
        "Runtime handoff is prepared only; runtime start requires observed runtime evidence.",
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
    "source-finder": (
        "I will prepare typed source candidates and acquisition status first: papers, links, datasets, repos, presentations, "
        "or docs/specs. Search, download, extraction, license checks, verification, and downstream processing stay unobserved "
        "until a wrapper or user records evidence."
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
        "I will surface stale, duplicate, cross-channel, or conflicting memory/context candidates with source, "
        "channel, and target scope before approve, reject, or update choices. Compacted summaries and recalled "
        "context are routing context, not proof of the current external source. Nothing is written until approval "
        "is observed."
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
    "run_omh_update": ("run_omh_update", "Run omh update"),
    "run_omh_setup": ("run_omh_setup", "Run omh setup"),
    "run_omh_doctor": ("run_omh_doctor", "Run omh doctor"),
    "run_omh_uninstall": ("run_omh_uninstall", "Run omh uninstall"),
    "run_omh_install": ("run_omh_install", "Run omh install"),
    "run_omh_list": ("run_omh_list", "Run omh list"),
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
    "prepare_source_finder_plan": ("prepare_source_finder_plan", "Prepare sources"),
    "prepare_paper_learning": ("prepare_paper_learning", "Prepare paper learning"),
    "prepare_material_package": ("prepare_material_package", "Prepare package"),
    "prepare_design_quality_gate": ("prepare_design_quality_gate", "Prepare design gate"),
    "prepare_frontend_handoff": ("prepare_frontend_handoff", "Prepare frontend"),
    "prepare_visual_qa": ("prepare_visual_qa", "Prepare visual QA"),
    "prepare_deliverable_package": ("prepare_deliverable_package", "Prepare deliverable"),
    "prepare_github_event_ops_card": ("prepare_github_event_ops_card", "Open event card"),
    "prepare_agent_board_card": ("prepare_agent_board_card", "Open agent board"),
    "prepare_executor_runtime_readiness": ("prepare_executor_runtime_readiness", "Check runtime"),
    "prepare_memory_curation_review": ("prepare_memory_curation_review", "Review memory"),
    "prepare_gateway_intent_card": ("prepare_gateway_intent_card", "Open gateway card"),
    "prepare_voice_operator_card": ("prepare_voice_operator_card", "Open voice card"),
    "prepare_toolbelt_readiness": ("prepare_toolbelt_readiness", "Check toolbelt"),
    "prepare_ops_observability_card": ("prepare_ops_observability_card", "Open observability"),
    "prepare_quality_performance_and_usability_review": (
        "prepare_quality_performance_and_usability_review",
        "Review performance",
    ),
    "refresh_status": ("refresh_status", "Refresh status"),
}

_OPERATING_BRIEF_CHAT_CARDS: dict[str, dict[str, object]] = {
    "ops-review": {
        "kind": "ops_review",
        "headline": "I can turn this into an operating review.",
        "body": (
            "I will prepare a compact operating review: observed status, customer signals, release risks, blockers, "
            "owners, and follow-up questions. Unknowns stay visible until source, owner, delivery, or runtime evidence "
            "is recorded."
        ),
        "phase": "ops_review_prepared",
        "next_action": "prepare_ops_review",
        "artifact_schema": "ops_review_card/v1",
        "actions": [
            {"id": "prepare_ops_review", "label": "Prepare ops review", "style": "primary"},
            {"id": "prepare_report_package", "label": "Prepare report", "style": "secondary"},
            {"id": "show_status", "label": "Show status", "style": "secondary"},
        ],
        "recommended_flow": [
            "summarize_observed_status",
            "name_customer_and_release_risks",
            "separate_blockers_from_unknowns",
            "assign_follow_up_owners",
        ],
        "evidence_not_observed": [
            "source status review",
            "customer signal review",
            "owner confirmation",
            "release decision",
            "follow-up completion",
            "implementation",
            "CI",
            "merge",
        ],
    },
    "strategy-brief": {
        "kind": "strategy_brief",
        "headline": "I can shape this into strategy options.",
        "body": (
            "I will prepare the strategy brief: decision frame, options, tradeoffs, assumptions, evidence gaps, "
            "decision owner, and open questions. Coding or delivery work stays disabled until a decision is accepted."
        ),
        "phase": "strategy_brief_prepared",
        "next_action": "prepare_strategy_brief",
        "artifact_schema": "strategy_brief_card/v1",
        "actions": [
            {"id": "prepare_strategy_brief", "label": "Prepare strategy", "style": "primary"},
            {"id": "prepare_meeting_brief", "label": "Prepare meeting brief", "style": "secondary"},
            {
                "id": "prepare_coding_handoff",
                "label": "Prepare coding handoff",
                "style": "secondary",
                "enabled": False,
                "payload": {"requires": "accepted decision and scoped implementation work"},
            },
            {"id": "show_status", "label": "Show status", "style": "secondary"},
        ],
        "recommended_flow": [
            "frame_decision",
            "list_options_and_tradeoffs",
            "name_evidence_gaps",
            "capture_decision_and_next_work",
        ],
        "evidence_not_observed": [
            "source-backed market evidence",
            "accepted decision",
            "stakeholder approval",
            "coding handoff",
            "implementation",
            "verification",
        ],
    },
    "report-package": {
        "kind": "report_package",
        "headline": "I can package this into a report people can review.",
        "body": (
            "I will prepare the report package: source inputs, narrative outline, missing numbers, reviewer checkpoints, "
            "export checklist, and delivery status. Binary export, visual QA, approval, and attachment remain observed-only."
        ),
        "phase": "report_package_prepared",
        "next_action": "prepare_report_package",
        "artifact_schema": "report_package_card/v1",
        "actions": [
            {"id": "prepare_report_package", "label": "Prepare report", "style": "primary"},
            {"id": "prepare_material_package", "label": "Prepare file package", "style": "secondary"},
            {"id": "show_status", "label": "Show status", "style": "secondary"},
        ],
        "recommended_flow": [
            "collect_source_inputs",
            "draft_report_outline",
            "mark_missing_numbers",
            "prepare_export_and_delivery_checks",
        ],
        "evidence_not_observed": [
            "source review completion",
            "stakeholder approval",
            "binary export",
            "render QA",
            "attachment or delivery",
            "publication",
        ],
    },
}

_OPERATING_BRIEF_WORKFLOW_BY_NEXT_ACTION = {
    str(config["next_action"]): workflow for workflow, config in _OPERATING_BRIEF_CHAT_CARDS.items()
}

_REVIEW_QUALITY_CHAT_CARDS: dict[str, dict[str, object]] = {
    "ultraqa": {
        "kind": "qa_review",
        "headline": "I can turn this into QA scenarios and observed checks.",
        "body": (
            "I will prepare the QA lane: scenario list, expected behavior, cheap checks, expensive checks, known gaps, "
            "and follow-up handoff options. No product diagnosis, verification, fix, CI, or release-readiness claim is made "
            "until matching observations exist."
        ),
        "phase": "qa_review_prepared",
        "next_action": "dispatch_to_workflow",
        "artifact_schema": "qa_review_card/v1",
        "actions": [
            {
                "id": "dispatch_to_workflow",
                "label": "Prepare QA workflow",
                "style": "primary",
                "payload": {"claim_boundary": "route_only_not_scenario_execution"},
            },
            {"id": "prepare_review_or_followup_handoff", "label": "Prepare follow-up review", "style": "secondary"},
            {"id": "show_status", "label": "Show status", "style": "secondary"},
        ],
        "recommended_flow": [
            "define_scenarios",
            "name_expected_behavior",
            "separate_observed_checks_from_gaps",
            "prepare_follow_up_handoff_if_needed",
        ],
        "evidence_not_observed": [
            "scenario execution",
            "product diagnosis",
            "observed checks",
            "fix implementation",
            "verification",
            "CI",
            "release readiness",
        ],
    },
    "code-review": {
        "kind": "review_check",
        "headline": "I can review the claims before we call this done.",
        "body": (
            "I will prepare a review lane: claims to inspect, evidence to verify, missing tests, risk areas, and any "
            "follow-up fix handoff. Review preparation is not a completed review, fix, CI result, or merge decision."
        ),
        "phase": "review_check_prepared",
        "next_action": "prepare_review_or_followup_handoff",
        "artifact_schema": "review_check_card/v1",
        "claim_boundary_suffix": "It is not verification, CI, merge-readiness, or merge evidence.",
        "actions": [
            {"id": "prepare_review_or_followup_handoff", "label": "Prepare review", "style": "primary"},
            {
                "id": "prepare_coding_handoff",
                "label": "Prepare fix handoff",
                "style": "secondary",
                "enabled": False,
                "payload": {"requires": "observed findings that require code changes"},
            },
            {"id": "show_status", "label": "Show status", "style": "secondary"},
        ],
        "recommended_flow": [
            "list_review_claims",
            "check_evidence",
            "separate_findings_from_fix_handoffs",
            "record_verification_gaps",
        ],
        "evidence_not_observed": [
            "completed review",
            "accepted findings",
            "fix implementation",
            "test execution",
            "CI",
            "merge readiness",
            "merge",
        ],
    },
    "reliability-review": {
        "kind": "reliability_review",
        "headline": "I can review reliability without declaring the system healthy.",
        "body": (
            "I will prepare the reliability review: service boundary, incident or SLO context, error-budget questions, "
            "risk hypotheses, remediation options, and verification gates. Healthy status, closure, or remediation success "
            "stays unobserved until evidence is recorded."
        ),
        "phase": "reliability_review_prepared",
        "next_action": "prepare_reliability_review",
        "artifact_schema": "reliability_review_card/v1",
        "actions": [
            {"id": "prepare_reliability_review", "label": "Review reliability", "style": "primary"},
            {"id": "prepare_review_or_followup_handoff", "label": "Prepare follow-up review", "style": "secondary"},
            {
                "id": "prepare_coding_handoff",
                "label": "Prepare remediation handoff",
                "style": "secondary",
                "enabled": False,
                "payload": {"requires": "accepted remediation scope and observed reliability evidence"},
            },
            {"id": "show_status", "label": "Show status", "style": "secondary"},
        ],
        "recommended_flow": [
            "define_service_boundary",
            "capture_slo_or_incident_context",
            "separate_risks_from_observed_health",
            "prepare_remediation_handoff_if_needed",
        ],
        "evidence_not_observed": [
            "SLO pass",
            "healthy error budget",
            "incident closure",
            "remediation completion",
            "verification",
            "review",
            "CI",
            "merge",
        ],
    },
}

_DELIVERY_RUNTIME_CHAT_CARDS: dict[str, dict[str, object]] = {
    "idea-to-deploy": {
        "kind": "app_delivery_loop",
        "headline": "I can shape this into a product delivery loop.",
        "body": (
            "I will prepare the idea-to-deploy loop: product intent, plan lane, implementation boundary, release gate, "
            "monitoring checks, rollback questions, and owner handoffs. This is not implementation, deploy, monitoring, "
            "or customer-impact evidence."
        ),
        "phase": "app_delivery_loop_prepared",
        "next_action": "present_app_delivery_loop",
        "artifact_schema": "app_delivery_loop_card/v1",
        "actions": [
            {"id": "present_app_delivery_loop", "label": "Show delivery loop", "style": "primary"},
            {
                "id": "prepare_coding_handoff",
                "label": "Prepare implementation handoff",
                "style": "secondary",
                "enabled": False,
                "payload": {"requires": "accepted product scope and implementation owner"},
            },
            {"id": "show_status", "label": "Show status", "style": "secondary"},
        ],
        "recommended_flow": [
            "shape_product_intent",
            "prepare_plan_lane",
            "separate_implementation_from_release",
            "define_monitoring_and_rollback_checks",
        ],
        "evidence_not_observed": [
            "accepted product scope",
            "implementation",
            "deployment",
            "monitoring",
            "rollback readiness",
            "customer impact",
            "CI",
        ],
    },
    "cto-loop": {
        "kind": "cto_loop",
        "headline": "I can run this as a leadership decision loop.",
        "body": (
            "I will prepare the CTO loop: roadmap question, architecture tradeoffs, delivery risk, security or reliability "
            "questions, release readiness gates, and decision owners. It is not stakeholder approval, architecture sign-off, "
            "implementation, or release evidence."
        ),
        "phase": "cto_loop_prepared",
        "next_action": "run_cto_loop",
        "artifact_schema": "cto_loop_card/v1",
        "actions": [
            {"id": "run_cto_loop", "label": "Open CTO loop", "style": "primary"},
            {"id": "prepare_strategy_brief", "label": "Prepare strategy", "style": "secondary"},
            {
                "id": "prepare_coding_handoff",
                "label": "Prepare implementation handoff",
                "style": "secondary",
                "enabled": False,
                "payload": {"requires": "accepted decision and scoped implementation work"},
            },
            {"id": "show_status", "label": "Show status", "style": "secondary"},
        ],
        "recommended_flow": [
            "frame_leadership_question",
            "compare_architecture_tradeoffs",
            "name_delivery_and_release_risks",
            "capture_decision_before_execution",
        ],
        "evidence_not_observed": [
            "stakeholder approval",
            "architecture sign-off",
            "implementation",
            "release readiness",
            "security review",
            "CI",
            "merge",
        ],
    },
    "deploy-and-monitor": {
        "kind": "deploy_monitor_plan",
        "headline": "I can prepare the deploy and monitor plan.",
        "body": (
            "I will prepare release operations: deploy intent, preflight gates, rollback plan, health checks, monitoring "
            "signals, incident fallback, and post-deploy review. This does not mean deploy, rollback, health, monitoring, "
            "or incident response has been observed."
        ),
        "phase": "deploy_monitor_plan_prepared",
        "next_action": "prepare_deploy_monitor_plan",
        "artifact_schema": "deploy_monitor_plan_card/v1",
        "actions": [
            {"id": "prepare_deploy_monitor_plan", "label": "Prepare deploy plan", "style": "primary"},
            {"id": "run_local_operator_check", "label": "Show local checks", "style": "secondary"},
            {"id": "show_status", "label": "Show status", "style": "secondary"},
        ],
        "recommended_flow": [
            "capture_release_intent",
            "list_preflight_gates",
            "define_health_signals",
            "separate_observed_deploy_from_plan",
        ],
        "evidence_not_observed": [
            "preflight pass",
            "deploy execution",
            "rollback readiness",
            "health check pass",
            "monitoring signal",
            "incident response",
            "post-deploy approval",
        ],
    },
    "executor-runtime-readiness": {
        "kind": "executor_runtime_readiness",
        "headline": "I can check which coding path is ready.",
        "body": (
            "I will prepare a runtime readiness card: Codex, Claude Code, Hermes, and generic runtime options; required "
            "tools; missing setup; fallback path; and what a wrapper can ask next. This is not executor dispatch, session "
            "attachment, implementation, verification, or CI evidence."
        ),
        "phase": "executor_runtime_readiness_prepared",
        "next_action": "prepare_executor_runtime_readiness",
        "artifact_schema": "executor_runtime_readiness_card/v1",
        "actions": [
            {"id": "prepare_executor_runtime_readiness", "label": "Check coding path", "style": "primary"},
            {"id": "choose_executor", "label": "Choose coding agent", "style": "secondary"},
            {"id": "show_status", "label": "Show status", "style": "secondary"},
        ],
        "recommended_flow": [
            "list_available_coding_paths",
            "check_missing_tools_without_dispatch",
            "choose_or_confirm_executor",
            "prepare_handoff_after_choice",
        ],
        "evidence_not_observed": [
            "executor dispatch",
            "session attachment",
            "implementation",
            "verification",
            "review",
            "CI",
            "merge",
        ],
    },
}

_WORKFLOW_OPERATIONS_CHAT_CARDS: dict[str, dict[str, object]] = {
    "automation-blueprint": {
        "kind": "automation_blueprint",
        "headline": "I can turn this into a scheduled ops blueprint.",
        "body": (
            "I will prepare the recurring workflow: schedule, source inputs, delivery target, silence policy, "
            "confirmation card, and status update rules. Host cron creation, source retrieval, gateway delivery, "
            "and no-agent execution stay observed-only."
        ),
        "phase": "automation_blueprint_prepared",
        "next_action": "prepare_scheduled_ops_blueprint",
        "artifact_schema": "automation_blueprint_card/v1",
        "claim_boundary_suffix": "It is not host cron creation, automation enablement, source retrieval, delivery, or no-agent execution evidence.",
        "actions": [
            {"id": "prepare_scheduled_ops_blueprint", "label": "Prepare automation", "style": "primary"},
            {"id": "prepare_toolbelt_readiness", "label": "Check toolbelt", "style": "secondary"},
            {"id": "show_status", "label": "Show status", "style": "secondary"},
        ],
        "recommended_flow": [
            "capture_schedule",
            "define_source_inputs",
            "set_delivery_and_silence_policy",
            "prepare_confirmation_card",
        ],
        "evidence_not_observed": [
            "host cron creation",
            "Hermes automation enablement",
            "source retrieval",
            "gateway delivery",
            "no-agent execution",
            "recipient receipt",
        ],
    },
    "agent-board": {
        "kind": "agent_board",
        "headline": "I can prepare a board for multiple Hermes agents.",
        "body": (
            "I will prepare the agent board: targets, roles, tasks, handoff lanes, heartbeat expectations, blocker "
            "states, and completion rules. Other agents accepting, working, heartbeat-ing, or completing work remains "
            "unobserved until target-specific evidence exists."
        ),
        "phase": "agent_board_prepared",
        "next_action": "prepare_agent_board_card",
        "artifact_schema": "agent_board_card/v1",
        "claim_boundary_suffix": "It is not target acceptance, agent heartbeat, task execution, blocker resolution, handoff receipt, or completion evidence.",
        "actions": [
            {"id": "prepare_agent_board_card", "label": "Open agent board", "style": "primary"},
            {"id": "refresh_status", "label": "Refresh status", "style": "secondary"},
            {"id": "show_status", "label": "Show status", "style": "secondary"},
        ],
        "recommended_flow": [
            "detect_targets",
            "assign_role_lanes",
            "record_task_and_handoff_states",
            "require_target_specific_heartbeat_evidence",
        ],
        "evidence_not_observed": [
            "target acceptance",
            "agent heartbeat",
            "task execution",
            "blocker resolution",
            "handoff receipt",
            "completion",
        ],
    },
    "memory-curation-review": {
        "kind": "memory_curation",
        "headline": "I can review memory and context before anything is changed.",
        "body": (
            "I will prepare a memory curation review: stale facts, duplicate notes, conflicting context, source scope, "
            "target/thread ownership, and approve/reject/update choices. Memory files, skill notes, and recalled context "
            "stay unchanged until an approved write is observed."
        ),
        "phase": "memory_curation_prepared",
        "next_action": "prepare_memory_curation_review",
        "artifact_schema": "memory_curation_card/v1",
        "claim_boundary_suffix": "It is not Hermes internal memory, MEMORY.md, USER.md, skill-file modification, approved memory write, or external source freshness evidence.",
        "actions": [
            {"id": "prepare_memory_curation_review", "label": "Review memory", "style": "primary"},
            {"id": "show_memory_status", "label": "Show memory status", "style": "secondary"},
            {"id": "show_status", "label": "Show status", "style": "secondary"},
        ],
        "recommended_flow": [
            "list_context_candidates",
            "classify_stale_duplicate_conflicting_items",
            "ask_for_approve_reject_update",
            "record_write_only_after_observed_approval",
        ],
        "evidence_not_observed": [
            "approved memory write",
            "MEMORY.md modification",
            "USER.md modification",
            "skill-file modification",
            "external source freshness",
            "Hermes internal memory update",
        ],
    },
    "gateway-intent-card": {
        "kind": "gateway_intent",
        "headline": "I can normalize this gateway intent before platform work.",
        "body": (
            "I will prepare the gateway intent: origin, thread key, delivery policy, silent updates, attachment rules, "
            "status-update behavior, and what the wrapper should ask next. Platform login, message sends, thread mutation, "
            "attachments, and delivery stay observed-only."
        ),
        "phase": "gateway_intent_prepared",
        "next_action": "prepare_gateway_intent_card",
        "artifact_schema": "gateway_intent_card/v1",
        "claim_boundary_suffix": "It is not platform login, message send, thread mutation, attachment upload, or delivery evidence.",
        "actions": [
            {"id": "prepare_gateway_intent_card", "label": "Open gateway card", "style": "primary"},
            {"id": "prepare_toolbelt_readiness", "label": "Check toolbelt", "style": "secondary"},
            {"id": "show_status", "label": "Show status", "style": "secondary"},
        ],
        "recommended_flow": [
            "normalize_origin_and_thread",
            "choose_delivery_and_silence_policy",
            "separate_attachment_rules_from_upload_evidence",
            "prepare_status_update_contract",
        ],
        "evidence_not_observed": [
            "platform login",
            "message send",
            "thread mutation",
            "attachment upload",
            "delivery",
            "recipient acknowledgement",
        ],
    },
    "deliverable-package": {
        "kind": "deliverable_package",
        "headline": "I can prepare the deliverable package and its delivery trail.",
        "body": (
            "I will prepare the deliverable path: required files, generation owner, export steps, render or formula QA, "
            "approval points, attachment status, and delivery evidence slots. Generated binaries, uploads, attachments, "
            "and approvals stay observed-only."
        ),
        "phase": "deliverable_package_prepared",
        "next_action": "prepare_deliverable_package",
        "artifact_schema": "deliverable_package_card/v1",
        "claim_boundary_suffix": "It is not binary generation, render QA, formula recalculation, approval, upload, attachment, or delivery evidence.",
        "actions": [
            {"id": "prepare_deliverable_package", "label": "Prepare deliverable", "style": "primary"},
            {"id": "prepare_material_package", "label": "Prepare source package", "style": "secondary"},
            {"id": "show_status", "label": "Show status", "style": "secondary"},
        ],
        "recommended_flow": [
            "inventory_required_files",
            "assign_generation_owner",
            "prepare_export_and_qa_checks",
            "record_attachment_and_delivery_evidence_slots",
        ],
        "evidence_not_observed": [
            "binary generation",
            "render QA",
            "formula recalculation",
            "approval",
            "upload",
            "attachment",
            "delivery",
        ],
    },
    "voice-operator": {
        "kind": "voice_operator",
        "headline": "I can turn the short request into a safe operator card.",
        "body": (
            "I will normalize the voice or mobile-style request into a concise clarify, plan, status, handoff, or "
            "confirmation action. Speech recognition, notification delivery, platform action, and risky execution stay "
            "unobserved until explicitly confirmed."
        ),
        "phase": "voice_operator_prepared",
        "next_action": "prepare_voice_operator_card",
        "artifact_schema": "voice_operator_card/v1",
        "claim_boundary_suffix": "It is not speech recognition proof, mobile notification delivery, platform action, or accepted execution evidence.",
        "actions": [
            {"id": "prepare_voice_operator_card", "label": "Open voice card", "style": "primary"},
            {"id": "answer:clarify", "label": "Ask/answer clarification", "style": "secondary"},
            {"id": "show_status", "label": "Show status", "style": "secondary"},
        ],
        "recommended_flow": [
            "normalize_short_input",
            "detect_risky_or_destructive_intent",
            "ask_one_confirmation_when_needed",
            "route_to_concrete_workflow_after_confirmation",
        ],
        "evidence_not_observed": [
            "speech recognition proof",
            "mobile notification delivery",
            "accepted execution",
            "platform action",
            "destructive approval",
            "workflow completion",
        ],
    },
    "toolbelt-readiness": {
        "kind": "toolbelt_readiness",
        "headline": "I can check the tools this workflow needs before claiming it can run.",
        "body": (
            "I will prepare the toolbelt readiness card: required MCP servers, CLIs, APIs, credentials, connectors, "
            "missing pieces, fallback mode, and safe setup next step. Installation, credential validation, API access, "
            "connector invocation, and workflow execution stay observed-only."
        ),
        "phase": "toolbelt_readiness_prepared",
        "next_action": "prepare_toolbelt_readiness",
        "artifact_schema": "toolbelt_readiness_card/v1",
        "claim_boundary_suffix": "It is not MCP installation, credential validation, API access, connector invocation, or successful workflow execution evidence.",
        "actions": [
            {"id": "prepare_toolbelt_readiness", "label": "Check toolbelt", "style": "primary"},
            {"id": "run_omh_doctor", "label": "Run doctor", "style": "secondary"},
            {"id": "show_status", "label": "Show status", "style": "secondary"},
        ],
        "recommended_flow": [
            "list_required_tools",
            "separate_installed_from_unobserved",
            "name_missing_credentials_or_connectors",
            "choose_safe_fallback_or_setup_step",
        ],
        "evidence_not_observed": [
            "MCP installation",
            "credential validation",
            "API access",
            "connector invocation",
            "workflow execution",
            "external service success",
        ],
    },
    "ops-observability-card": {
        "kind": "ops_observability",
        "headline": "I can prepare observability without inventing provider truth.",
        "body": (
            "I will prepare a wrapper-safe observability card: token, cost, latency, run history, queue, failure modes, "
            "external metric-provider payloads, service-quality gaps, and evidence boundaries. Local estimates and supplied "
            "metric exports stay separate from provider billing, quota truth, live metric-provider access, full tracing, "
            "SLO pass, incident closure, remediation completion, performance proof, and workflow completion."
        ),
        "phase": "ops_observability_prepared",
        "next_action": "prepare_ops_observability_card",
        "artifact_schema": "ops_service_quality_board/v1",
        "claim_boundary_suffix": "It is not provider billing truth, provider quota truth, live metric-provider access, complete tracing, SLO pass, incident closure, remediation completion, performance proof, or workflow completion evidence.",
        "actions": [
            {"id": "prepare_ops_observability_card", "label": "Open observability", "style": "primary"},
            {"id": "refresh_status", "label": "Refresh status", "style": "secondary"},
            {"id": "show_status", "label": "Show status", "style": "secondary"},
        ],
        "recommended_flow": [
            "collect_local_runtime_records",
            "accept_external_metric_provider_payloads",
            "separate_estimates_from_provider_truth",
            "type_service_quality_downgrade_gaps",
            "summarize_failure_modes",
            "mark_missing_trace_or_billing_evidence",
        ],
        "evidence_not_observed": [
            "provider billing truth",
            "provider quota truth",
            "live metric-provider access",
            "complete tracing",
            "SLO pass",
            "incident closure",
            "remediation completion",
            "performance proof",
            "workflow completion",
            "external telemetry fetch",
        ],
    },
    "operating-rhythm": {
        "kind": "operating_rhythm",
        "headline": "I can turn this into an operating rhythm record.",
        "body": (
            "I will prepare the operating rhythm: cadence, meeting topics, decisions, owners, follow-up slots, "
            "and what needs confirmation. Meeting outcomes, owner acceptance, and completed follow-ups stay unobserved "
            "until recorded."
        ),
        "phase": "operating_rhythm_prepared",
        "next_action": "prepare_operating_record",
        "artifact_schema": "operating_rhythm_card/v1",
        "claim_boundary_suffix": "It is not meeting completion, decision approval, owner acceptance, or follow-up evidence.",
        "actions": [
            {"id": "prepare_operating_record", "label": "Prepare rhythm", "style": "primary"},
            {"id": "prepare_report_package", "label": "Prepare record package", "style": "secondary"},
            {"id": "show_status", "label": "Show status", "style": "secondary"},
        ],
        "recommended_flow": [
            "capture_cadence",
            "list_meeting_topics",
            "separate_decisions_from_open_questions",
            "record_owner_follow_up_slots",
        ],
        "evidence_not_observed": [
            "meeting completion",
            "decision approval",
            "owner acceptance",
            "follow-up completion",
            "source notes reviewed",
            "delivery",
        ],
    },
    "materials-package": {
        "kind": "materials_package",
        "headline": "I can prepare the material package without pretending files exist.",
        "body": (
            "I will prepare the material package: source files, target formats, extraction needs, formulas or layout risks, "
            "export checklist, render QA, approval, and delivery steps. Binary files, uploads, render checks, and attachments "
            "remain observed-only."
        ),
        "phase": "materials_package_prepared",
        "next_action": "prepare_material_package",
        "artifact_schema": "materials_package_card/v1",
        "claim_boundary_suffix": "It is not binary export, render QA, upload, attachment, approval, or delivery evidence.",
        "actions": [
            {"id": "prepare_material_package", "label": "Prepare package", "style": "primary"},
            {"id": "prepare_deliverable_package", "label": "Prepare deliverable", "style": "secondary"},
            {"id": "show_status", "label": "Show status", "style": "secondary"},
        ],
        "recommended_flow": [
            "inventory_source_files",
            "choose_target_formats",
            "name_extraction_or_layout_risks",
            "prepare_export_and_render_qa_checks",
        ],
        "evidence_not_observed": [
            "source extraction",
            "binary export",
            "formula validation",
            "render QA",
            "upload",
            "attachment",
            "approval",
        ],
    },
    "research-department": {
        "kind": "research_department",
        "headline": "I can organize this into a research department flow.",
        "body": (
            "I will prepare Scout, Analyst, and Briefer lanes: source inbox, synthesis questions, briefing format, cadence, "
            "knowledge-store readiness, and delivery policy. Source retrieval, synthesis, verification, storage, and delivery "
            "stay unobserved until recorded."
        ),
        "phase": "research_department_prepared",
        "next_action": "prepare_research_department_plan",
        "artifact_schema": "research_department_card/v1",
        "claim_boundary_suffix": "It is not source retrieval, synthesis, verification, knowledge-store write, or delivery evidence.",
        "actions": [
            {"id": "prepare_research_department_plan", "label": "Prepare research flow", "style": "primary"},
            {"id": "run_hermes_research", "label": "Start research", "style": "secondary"},
            {"id": "prepare_report_package", "label": "Prepare brief", "style": "secondary"},
            {"id": "show_status", "label": "Show status", "style": "secondary"},
        ],
        "recommended_flow": [
            "define_scout_sources",
            "prepare_analyst_questions",
            "choose_briefing_format",
            "separate_retrieval_from_synthesis_and_delivery",
        ],
        "evidence_not_observed": [
            "source retrieval",
            "source verification",
            "synthesis",
            "knowledge-store write",
            "brief delivery",
            "stakeholder approval",
        ],
    },
    "github-event-ops": {
        "kind": "github_event_ops",
        "headline": "I can prepare this GitHub event without claiming webhook work happened.",
        "body": (
            "I will prepare the GitHub event card: event type, issue or PR context, triage labels, review path, CI questions, "
            "docs-sync needs, and follow-up handoff. Webhook receipt, GitHub mutation, code changes, review, CI, and docs sync "
            "stay observed-only."
        ),
        "phase": "github_event_ops_prepared",
        "next_action": "prepare_github_event_ops_card",
        "artifact_schema": "github_event_ops_card/v1",
        "claim_boundary_suffix": "It is not webhook receipt, webhook delivery, GitHub mutation, code execution, review, CI, docs-sync, or merge evidence.",
        "actions": [
            {"id": "prepare_github_event_ops_card", "label": "Open event card", "style": "primary"},
            {"id": "prepare_review_or_followup_handoff", "label": "Prepare review", "style": "secondary"},
            {
                "id": "prepare_coding_handoff",
                "label": "Prepare fix handoff",
                "style": "secondary",
                "enabled": False,
                "payload": {"requires": "observed event context and accepted implementation scope"},
            },
            {"id": "show_status", "label": "Show status", "style": "secondary"},
        ],
        "recommended_flow": [
            "classify_github_event",
            "prepare_triage_or_review_path",
            "separate_ci_and_docs_questions",
            "prepare_follow_up_handoff_if_scope_is_accepted",
        ],
        "evidence_not_observed": [
            "webhook receipt",
            "GitHub mutation",
            "label application",
            "code execution",
            "completed review",
            "CI",
            "docs sync",
            "merge",
        ],
    },
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
    if _can_use_chat_interaction_cache(
        event_or_message,
        include_message=include_message,
        source_metadata=source_metadata,
        target_notice=target_notice,
        paths=paths,
    ):
        return _copy_chat_interaction_payload(
            _build_chat_interaction_payload_cached(
                message,
                source,
                mode,
                limit,
                min_confidence,
                executor_target,
            )
        )

    return _build_chat_interaction_payload_uncached(
        event_or_message,
        source=source,
        mode=mode,
        limit=limit,
        min_confidence=min_confidence,
        include_message=include_message,
        executor_target=executor_target,
        source_metadata=source_metadata,
        target_notice=target_notice,
        paths=paths,
    )


def _can_use_chat_interaction_cache(
    event_or_message: dict[str, Any] | str,
    *,
    include_message: bool,
    source_metadata: dict[str, str] | None,
    target_notice: dict[str, object] | None,
    paths: OmhPaths | None,
) -> bool:
    return (
        isinstance(event_or_message, str)
        and not include_message
        and source_metadata is None
        and target_notice is None
        and paths is None
    )


def _copy_chat_interaction_payload(payload: dict[str, object]) -> dict[str, object]:
    copied = dict(payload)
    handled = {
        "source_metadata",
        "overclaim_guard",
        "route",
        "executor_resolution",
        "chat_response",
    }

    source_metadata = copied.get("source_metadata")
    if isinstance(source_metadata, dict):
        copied["source_metadata"] = dict(source_metadata)

    overclaim_guard = copied.get("overclaim_guard")
    if isinstance(overclaim_guard, list):
        copied["overclaim_guard"] = list(overclaim_guard)

    route = copied.get("route")
    if isinstance(route, dict):
        copied["route"] = _copy_chat_interaction_route(route)

    executor_resolution = copied.get("executor_resolution")
    if isinstance(executor_resolution, dict):
        copied["executor_resolution"] = dict(executor_resolution)

    response = copied.get("chat_response")
    if isinstance(response, dict):
        copied["chat_response"] = _copy_chat_response_payload(response)

    for key, value in list(copied.items()):
        if key in handled:
            continue
        if isinstance(value, dict):
            copied[key] = _clone_static_dict(value)
        elif isinstance(value, list):
            copied[key] = _clone_static_payload(value)
    return copied


def _copy_chat_interaction_route(route: dict[str, object]) -> dict[str, object]:
    copied = dict(route)
    recommendations = route.get("recommendations")
    copied["recommendations"] = _copy_recommendation_list(recommendations)

    route_explanation = route.get("route_explanation")
    if isinstance(route_explanation, dict):
        copied["route_explanation"] = _copy_workflow_explanation_like(route_explanation)

    workflow_route_plan = route.get("workflow_route_plan")
    if isinstance(workflow_route_plan, dict):
        copied["workflow_route_plan"] = _copy_workflow_route_plan_payload(workflow_route_plan)

    for key in ("task_card", "learning_candidate_card"):
        value = route.get(key)
        if isinstance(value, dict):
            copied[key] = _clone_static_dict(value)
    return copied


def _copy_chat_response_payload(response: dict[str, object]) -> dict[str, object]:
    copied = dict(response)
    state = response.get("state")
    if isinstance(state, dict):
        copied["state"] = _copy_chat_response_state(state)

    usage_trace = response.get("usage_trace")
    if isinstance(usage_trace, dict):
        copied["usage_trace"] = dict(usage_trace)

    messenger_rendering = response.get("messenger_rendering")
    if isinstance(messenger_rendering, dict):
        copied["messenger_rendering"] = _copy_messenger_rendering_payload(messenger_rendering)

    actions = response.get("actions")
    if isinstance(actions, list):
        copied["actions"] = _copy_action_list(actions)

    status_card = response.get("status_card")
    if isinstance(status_card, dict):
        copied["status_card"] = _clone_static_dict(status_card)
    return copied


def _copy_chat_response_state(state: dict[str, object]) -> dict[str, object]:
    copied = dict(state)

    for key in (
        "direct_invocation_aliases",
        "evidence_not_observed",
        "recommended_flow",
        "next_steps",
        "missing_evidence",
    ):
        value = state.get(key)
        if isinstance(value, list):
            copied[key] = list(value)

    for key in ("executor_resolution", "source_metadata"):
        value = state.get(key)
        if isinstance(value, dict):
            copied[key] = dict(value)

    workflow_explanation = state.get("workflow_explanation")
    if isinstance(workflow_explanation, dict):
        copied["workflow_explanation"] = _copy_workflow_explanation_like(workflow_explanation)

    context_primer = state.get("context_primer")
    if isinstance(context_primer, dict):
        copied["context_primer"] = _copy_context_primer_payload(context_primer)

    skill_picker = state.get("skill_picker")
    if isinstance(skill_picker, dict):
        copied["skill_picker"] = _copy_skill_picker_payload(skill_picker)

    capability_summary = state.get("capability_summary")
    if isinstance(capability_summary, dict):
        copied["capability_summary"] = _copy_catalog_capability_summary_payload(capability_summary)

    for key, value in list(copied.items()):
        if key in {
            "direct_invocation_aliases",
            "evidence_not_observed",
            "recommended_flow",
            "next_steps",
            "missing_evidence",
            "executor_resolution",
            "source_metadata",
            "workflow_explanation",
            "context_primer",
            "skill_picker",
            "capability_summary",
        }:
            continue
        if isinstance(value, dict):
            copied[key] = _clone_static_dict(value)
        elif isinstance(value, list):
            copied[key] = _clone_static_payload(value)
    return copied


def _copy_recommendation_list(value: object) -> list[dict[str, object]]:
    copied: list[dict[str, object]] = []
    if not isinstance(value, list):
        return copied
    for item in value:
        if not isinstance(item, dict):
            continue
        recommendation = dict(item)
        matched = recommendation.get("matched")
        recommendation["matched"] = list(matched) if isinstance(matched, list) else []
        copied.append(recommendation)
    return copied


def _copy_workflow_explanation_like(value: dict[str, object]) -> dict[str, object]:
    copied = dict(value)
    not_evidence_yet = value.get("not_evidence_yet")
    copied["not_evidence_yet"] = list(not_evidence_yet) if isinstance(not_evidence_yet, list) else []
    context_card = value.get("workflow_context_card")
    if isinstance(context_card, dict):
        copied["workflow_context_card"] = _copy_workflow_context_card(context_card)
    return copied


def _copy_workflow_route_plan_payload(value: dict[str, object]) -> dict[str, object]:
    copied = dict(value)
    steps = value.get("steps")
    copied["steps"] = [_copy_route_plan_step(item) for item in steps if isinstance(item, dict)] if isinstance(steps, list) else []
    stages = value.get("stages")
    copied["stages"] = list(stages) if isinstance(stages, list) else []
    return copied


def _copy_route_plan_step(step: dict[str, object]) -> dict[str, object]:
    copied = dict(step)
    matched = step.get("matched")
    if isinstance(matched, list):
        copied["matched"] = list(matched)
    return copied


def _copy_action_list(value: object) -> list[dict[str, object]]:
    copied: list[dict[str, object]] = []
    if not isinstance(value, list):
        return copied
    for item in value:
        if not isinstance(item, dict):
            continue
        action = dict(item)
        payload = action.get("payload")
        if isinstance(payload, dict):
            action["payload"] = _copy_action_payload(payload)
        copied.append(action)
    return copied


def _copy_action_payload(value: dict[str, object]) -> dict[str, object]:
    copied = dict(value)
    handled = {"options", "featured_options", "capability_families", "groups", "input_schema"}
    if "options" in copied:
        copied["options"] = _copy_picker_options(value.get("options"))
    if "featured_options" in copied:
        copied["featured_options"] = _copy_compact_picker_options(value.get("featured_options"))
    if "capability_families" in copied:
        copied["capability_families"] = _copy_family_cards(value.get("capability_families"))
    if "groups" in copied:
        copied["groups"] = _copy_picker_groups(value.get("groups"))
    input_schema = value.get("input_schema")
    if isinstance(input_schema, dict):
        copied["input_schema"] = dict(input_schema)
    for key, item in list(copied.items()):
        if key in handled:
            continue
        if isinstance(item, dict):
            copied[key] = _clone_static_dict(item)
        elif isinstance(item, list):
            copied[key] = _clone_static_payload(item)
    return copied


def _copy_skill_picker_payload(value: dict[str, object]) -> dict[str, object]:
    copied = dict(value)
    copied["options"] = _copy_picker_options(value.get("options"))
    copied["featured_options"] = _copy_compact_picker_options(value.get("featured_options"))
    copied["capability_families"] = _copy_family_cards(value.get("capability_families"))
    copied["groups"] = _copy_picker_groups(value.get("groups"))
    rendering_hints = value.get("rendering_hints")
    if isinstance(rendering_hints, dict):
        copied["rendering_hints"] = dict(rendering_hints)
    return copied


def _copy_picker_options(value: object) -> list[dict[str, object]]:
    copied: list[dict[str, object]] = []
    if not isinstance(value, list):
        return copied
    for item in value:
        if not isinstance(item, dict):
            continue
        option = dict(item)
        payload = option.get("payload")
        if isinstance(payload, dict):
            option["payload"] = dict(payload)
        copied.append(option)
    return copied


def _copy_compact_picker_options(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _copy_picker_groups(value: object) -> list[dict[str, object]]:
    copied: list[dict[str, object]] = []
    if not isinstance(value, list):
        return copied
    for item in value:
        if not isinstance(item, dict):
            continue
        group = dict(item)
        option_ids = group.get("option_ids")
        if isinstance(option_ids, list):
            group["option_ids"] = list(option_ids)
        group["options"] = _copy_compact_picker_options(group.get("options"))
        copied.append(group)
    return copied


def _copy_context_primer_payload(value: dict[str, object]) -> dict[str, object]:
    copied = dict(value)
    copied["capability_families"] = _copy_family_cards(value.get("capability_families"))
    copied["workflow_groups"] = _copy_workflow_groups(value.get("workflow_groups"))
    copied["workflow_context_cards"] = _copy_workflow_context_cards(value.get("workflow_context_cards"))
    return copied


def _copy_catalog_capability_summary_payload(value: dict[str, object]) -> dict[str, object]:
    copied = dict(value)
    copied["capability_families"] = _copy_family_cards(value.get("capability_families"))
    copied["lanes"] = _copy_capability_lanes(value.get("lanes"))
    copied["workflow_context_cards"] = _copy_workflow_context_cards(value.get("workflow_context_cards"))
    for key in ("direct_response_guidance", "evidence_boundary"):
        items = value.get(key)
        if isinstance(items, list):
            copied[key] = list(items)
    return copied


def _copy_family_cards(value: object) -> list[dict[str, object]]:
    copied: list[dict[str, object]] = []
    if not isinstance(value, list):
        return copied
    for item in value:
        if not isinstance(item, dict):
            continue
        card = dict(item)
        primary_workflows = card.get("primary_workflows")
        if isinstance(primary_workflows, list):
            card["primary_workflows"] = list(primary_workflows)
        executor_choices = card.get("executor_choices")
        if isinstance(executor_choices, list):
            card["executor_choices"] = list(executor_choices)
        copied.append(card)
    return copied


def _copy_workflow_groups(value: object) -> list[dict[str, object]]:
    copied: list[dict[str, object]] = []
    if not isinstance(value, list):
        return copied
    for item in value:
        if not isinstance(item, dict):
            continue
        group = dict(item)
        workflows = group.get("workflows")
        if isinstance(workflows, (list, tuple)):
            group["workflows"] = tuple(workflows)
        copied.append(group)
    return copied


def _copy_workflow_context_cards(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [_copy_compact_workflow_context_card(item) for item in value if isinstance(item, dict)]


def _copy_workflow_context_card(value: dict[str, object]) -> dict[str, object]:
    copied = dict(value)
    for key in ("representative_workflows", "user_examples", "not_evidence_until_observed"):
        copied[key] = _copy_string_items(value.get(key))
    return copied


def _copy_compact_workflow_context_card(value: dict[str, object]) -> dict[str, object]:
    return {
        "id": str(value.get("id", "")),
        "label": str(value.get("label", "")),
        "user_signal": _trim_catalog_text(value.get("user_signal"), 96),
        "omh_pattern": _trim_catalog_text(value.get("omh_pattern"), 112),
        "representative_workflows": _copy_string_items(value.get("representative_workflows")),
        "user_examples": _copy_string_items(value.get("user_examples"), limit=1),
        "first_response_shape": _trim_catalog_text(value.get("first_response_shape"), 140),
        "not_evidence_until_observed": _copy_string_items(value.get("not_evidence_until_observed")),
    }


def _copy_string_items(value: object, *, limit: int | None = None) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    items = [item for item in value if isinstance(item, str) and item]
    return items if limit is None else items[:limit]


def _trim_catalog_text(value: object, max_chars: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_chars:
        return text
    trimmed = text[:max_chars].rsplit(" ", 1)[0].strip()
    return trimmed or text[:max_chars].strip()


def _copy_capability_lanes(value: object) -> list[dict[str, object]]:
    copied: list[dict[str, object]] = []
    if not isinstance(value, list):
        return copied
    for item in value:
        if not isinstance(item, dict):
            continue
        lane = dict(item)
        for key in ("primary_skills", "wrapper_actions", "examples"):
            items = lane.get(key)
            if isinstance(items, list):
                lane[key] = list(items)
        playbooks = lane.get("representative_playbooks")
        if isinstance(playbooks, list):
            lane["representative_playbooks"] = _copy_representative_playbooks(playbooks)
        copied.append(lane)
    return copied


def _copy_representative_playbooks(value: list[object]) -> list[dict[str, object]]:
    copied: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        playbook = dict(item)
        first_stage = playbook.get("first_stage")
        if isinstance(first_stage, dict):
            playbook["first_stage"] = dict(first_stage)
        copied.append(playbook)
    return copied


def _copy_messenger_rendering_payload(value: dict[str, object]) -> dict[str, object]:
    copied = dict(value)
    for key in ("body_blocks", "fallback_body_blocks"):
        blocks = value.get(key)
        if isinstance(blocks, list):
            copied[key] = [dict(block) for block in blocks if isinstance(block, dict)]
    for key in (
        "preferred_blocks",
        "avoid_blocks",
        "transforms_applied",
        "fallback_transforms_applied",
    ):
        items = value.get(key)
        if isinstance(items, list):
            copied[key] = list(items)
    chunking = value.get("chunking")
    if isinstance(chunking, dict):
        copied["chunking"] = dict(chunking)
        split_on = chunking.get("split_on")
        if isinstance(split_on, list):
            copied["chunking"]["split_on"] = list(split_on)
    for key in ("prefix_policy", "platform_hints"):
        item = value.get(key)
        if isinstance(item, dict):
            copied[key] = dict(item)
    return copied


@lru_cache(maxsize=2048)
def _build_chat_interaction_payload_cached(
    message: str,
    source: str,
    mode: str,
    limit: int,
    min_confidence: str,
    executor_target: str,
) -> dict[str, object]:
    return _build_chat_interaction_payload_uncached(
        message,
        source=source,
        mode=mode,
        limit=limit,
        min_confidence=min_confidence,
        include_message=False,
        executor_target=executor_target,
        source_metadata=None,
        target_notice=None,
        paths=None,
    )


def _build_chat_interaction_payload_uncached(
    event_or_message: dict[str, Any] | str,
    *,
    source: str,
    mode: str,
    limit: int,
    min_confidence: str,
    include_message: bool,
    executor_target: str,
    source_metadata: dict[str, str] | None,
    target_notice: dict[str, object] | None,
    paths: OmhPaths | None,
) -> dict[str, object]:
    message = extract_message_text(event_or_message)
    metadata = _source_metadata(event_or_message, source_metadata)
    route_payload = public_chat_route_payload(
        message,
        source=source,
        limit=limit,
        min_confidence=min_confidence,
        include_message=include_message,
    )
    resolved_mode = _resolve_mode(mode, route_payload, message=message)
    base = _base_interaction(message, source=source, source_metadata=metadata, mode=resolved_mode, include_message=include_message)
    if (
        _is_generic_skill_catalog_route(message, route_payload)
        and _route_recommendation_next_action(route_payload) != "show_command_preview"
    ):
        route_payload = _catalog_question_route_payload(route_payload)
    base["route"] = route_payload
    if isinstance(route_payload.get("task_card"), dict):
        base["task_card"] = route_payload["task_card"]
    learning_candidate_card = build_learning_candidate_card(
        message,
        source=source,
        source_metadata=metadata,
        selected_workflow=str(route_payload.get("selected_skill", "")),
        selected_harness=str(route_payload.get("selected_harness", "")),
        thread_key=str(base["thread_key"]),
    )
    if (
        learning_candidate_card
        and route_payload.get("selected_skill") == "workflow-learning"
        and learning_candidate_card.get("recommended_workflow") != "workflow-learning"
    ):
        learning_candidate_card = None
    if learning_candidate_card:
        base["learning_candidate_card"] = learning_candidate_card
        route_payload["learning_candidate_card"] = learning_candidate_card

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

    resolved_executor_target, executor_resolution = _resolve_delegate_executor_target(executor_target, paths, message=message)

    if resolved_mode == "delegate":
        delegation = build_coding_delegation_payload(
            message,
            source=source,
            limit=limit,
            include_message=include_message,
            source_metadata=metadata,
            executor_target=resolved_executor_target,
            memory_recall_pack=memory_recall_pack_for_handoff(
                paths,
                message,
                executor_target=resolved_executor_target,
            )
            if paths
            else None,
        )
        delegation["executor_resolution"] = executor_resolution
        base["delegation"] = delegation
        base["executor_resolution"] = executor_resolution
        agentic_playbook = delegation.get("agentic_playbook")
        if isinstance(agentic_playbook, dict):
            base["agentic_playbook"] = agentic_playbook
        base["next_action"] = _delegation_next_action(delegation)
        base["chat_response"] = build_chat_response_from_delegation(delegation, thread_key=str(base["thread_key"]))
        return _finish_interaction(base, target_notice)

    if resolved_mode == "clarify" or route_payload["action"] != "dispatch":
        base["chat_response"] = build_chat_response_from_route(
            route_payload,
            thread_key=str(base["thread_key"]),
            message=message,
            include_message=include_message,
        )
        agentic_playbook = maybe_build_agentic_playbook(message, route_payload=route_payload)
        if agentic_playbook:
            base["agentic_playbook"] = agentic_playbook
        base["next_action"] = str(_nested(base["chat_response"], "state").get("next_action", "answer_clarification"))
        return _finish_interaction(base, target_notice)

    if resolved_mode == "route":
        route_response = build_chat_response_from_route(
            route_payload,
            thread_key=str(base["thread_key"]),
            message=message,
            include_message=include_message,
        )
        if _route_requires_coding_owner(route_payload, route_response, message):
            return _finish_interaction(
                _attach_coding_owner_handoff(
                    base,
                    message,
                    source=source,
                    limit=limit,
                    include_message=include_message,
                    source_metadata=metadata,
                    resolved_executor_target=resolved_executor_target,
                    executor_resolution=executor_resolution,
                    route_payload=route_payload,
                    paths=paths,
                ),
                target_notice,
            )
        base["chat_response"] = route_response
        base["next_action"] = str(_nested(base["chat_response"], "state").get("next_action", "dispatch_to_workflow"))
        loop_start_card = _nested(_nested(base["chat_response"], "state"), "loop_start_card")
        if loop_start_card:
            base["loop_start_card"] = loop_start_card
        return _finish_interaction(base, target_notice)

    plan = build_hermes_plan_payload(
        message,
        source=source,
        limit=limit,
        source_metadata=metadata,
        executor_target=resolved_executor_target,
    )
    if _plan_has_coding_delegate(plan):
        coding_delegate = _nested(_nested(plan, "wrapper_contract"), "coding_delegate")
        coding_delegate["executor_resolution"] = executor_resolution
        base["executor_resolution"] = executor_resolution
    base["plan"] = _public_plan_payload(plan, include_message=include_message)
    contract = _nested(plan, "wrapper_contract")
    coding_delegate = _nested(contract, "coding_delegate")
    agentic_playbook = maybe_build_agentic_playbook(
        message,
        route_payload=route_payload,
        delegation_payload=coding_delegate if coding_delegate else None,
    )
    if agentic_playbook:
        base["agentic_playbook"] = agentic_playbook
    next_action = str(contract.get("next_action", "present_plan"))
    base["next_action"] = "present_plan" if next_action == "prepare_coding_delegation_after_plan_acceptance" else next_action
    base["chat_response"] = build_chat_response_from_plan(plan, thread_key=str(base["thread_key"]))
    return _finish_interaction(base, target_notice)


def _resolve_delegate_executor_target(executor_target: str, paths: OmhPaths | None, *, message: str = "") -> tuple[str, dict[str, object]]:
    requested = str(executor_target or "choose").strip() or "choose"
    message_hint = _executor_target_from_message(message)
    setup_default = "choose"
    setup_available = False
    if paths is not None:
        try:
            profile = read_setup_profile(paths)
        except (OSError, ValueError):
            profile = None
        if isinstance(profile, dict):
            candidate = str(profile.get("default_executor", "") or "").strip()
            if candidate in CODING_EXECUTOR_TARGETS:
                setup_default = candidate
                setup_available = True

    if requested != "choose":
        resolved = requested
        source = "explicit"
    elif message_hint:
        resolved = message_hint
        source = "message_mention"
    elif setup_available:
        resolved = setup_default
        source = "setup_profile"
    else:
        resolved = "choose"
        source = "caller_default"

    return resolved, {
        "schema_version": "executor_resolution/v1",
        "source": source,
        "requested_executor_target": requested,
        "message_executor_target": message_hint,
        "default_executor": setup_default,
        "resolved_executor_target": resolved,
        "explicit_override": requested != "choose",
        "claim_boundary": "Executor default resolution is routing preference only; it is not dispatch, execution, review, CI, or merge evidence.",
    }


@lru_cache(maxsize=4096)
def _executor_target_from_message(message: str) -> str:
    lowered = f" {message.lower()} "
    for target, hints in _MESSAGE_EXECUTOR_HINTS:
        if any(hint in lowered for hint in hints):
            return target
    return ""


def _attach_coding_owner_handoff(
    base: dict[str, object],
    message: str,
    *,
    source: str,
    limit: int,
    include_message: bool,
    source_metadata: dict[str, str],
    resolved_executor_target: str,
    executor_resolution: dict[str, object],
    route_payload: dict[str, object],
    paths: OmhPaths | None,
) -> dict[str, object]:
    delegation = build_coding_delegation_payload(
        message,
        source=source,
        limit=limit,
        include_message=include_message,
        source_metadata=source_metadata,
        executor_target=resolved_executor_target,
        force_coding_handoff=True,
        preferred_workflow=str(route_payload.get("selected_skill", "")),
        preferred_workflow_score=_intish(route_payload.get("score", 0)),
        memory_recall_pack=memory_recall_pack_for_handoff(
            paths,
            message,
            executor_target=resolved_executor_target,
        )
        if paths
        else None,
    )
    delegation["executor_resolution"] = executor_resolution
    delegation["route_context"] = {
        "schema_version": "coding_route_context/v1",
        "selected_skill": route_payload.get("selected_skill", ""),
        "reason": route_payload.get("reason", ""),
        "coding_status_request": _route_is_coding_status_request(route_payload),
        "claim_boundary": "Route context explains why the wrapper shaped this handoff; it is not dispatch or runtime evidence.",
    }
    agentic_playbook = delegation.get("agentic_playbook")
    if isinstance(agentic_playbook, dict):
        base["agentic_playbook"] = agentic_playbook
    base["delegation"] = delegation
    base["executor_resolution"] = executor_resolution
    base["next_action"] = _delegation_next_action(delegation)
    base["chat_response"] = build_chat_response_from_delegation(delegation, thread_key=str(base["thread_key"]))
    return base


def _delegation_next_action(delegation: dict[str, object]) -> str:
    action = str(_nested(delegation, "delegation").get("action", "fallback"))
    if action == "delegate" and _delegation_is_coding_status_request(delegation):
        return "show_coding_handoff_status"
    if action == "delegate" and delegation.get("executor_handoff"):
        return "send_to_executor"
    if action == "delegate" and delegation.get("runtime_handoff"):
        return "show_runtime_handoff"
    if action == "delegate" and delegation.get("prompt_handoff"):
        return "show_prompt_handoff"
    if action == "delegate" and _nested(delegation, "executor_selection").get("choice_required"):
        return "choose_executor"
    if action == "clarify":
        return "answer_clarification"
    return "route_coding_request"


def _route_requires_coding_owner(route_payload: dict[str, object], route_response: dict[str, object], message: str) -> bool:
    if str(route_payload.get("action", "")) != "dispatch":
        return False
    selected = str(route_payload.get("selected_skill", "") or _nested(route_response, "state").get("selected_workflow", ""))
    policy_next_action = str(_nested(route_response, "state").get("policy_next_action", ""))
    if _route_is_coding_status_request(route_payload) and not _executor_target_from_message(message):
        return False
    if selected in _CODING_OWNER_WORKFLOWS:
        return True
    if policy_next_action in _CODING_OWNER_NEXT_ACTIONS:
        return True
    if selected in _CODING_OWNER_WHEN_CODE_SHAPED:
        return is_coding_shaped_task(message)
    return False


def _route_is_coding_status_request(route_payload: dict[str, object]) -> bool:
    reason = str(route_payload.get("reason", "")).lower()
    if "coding progress questions" in reason or "progress/status" in reason:
        return True
    for recommendation in route_payload.get("recommendations", []):
        if not isinstance(recommendation, dict):
            continue
        matched = {str(item) for item in recommendation.get("matched", []) if str(item)}
        if {"guard:coding_progress_status", "guard:coding_handoff_status"} & matched:
            return True
    return False


def _route_is_explicit_hermes_coding_team_request(route_payload: dict[str, object], message: str) -> bool:
    selected = str(route_payload.get("selected_skill", ""))
    if selected != "team":
        return False
    for recommendation in route_payload.get("recommendations", []):
        if not isinstance(recommendation, dict) or str(recommendation.get("skill", "")) != "team":
            continue
        matched = {str(item) for item in recommendation.get("matched", []) if str(item)}
        if "guard:hermes_coding_team" in matched:
            return True

    lowered = f" {message.lower()} "
    team_terms = (
        "coding team",
        "team mode",
        "team runtime",
        "코딩팀",
        "코딩 팀",
        "팀처럼",
        "팀으로",
        "팀 모드",
    )
    coding_terms = ("coding", "code", "refactor", "implementation", "코딩", "구현", "개발", "리팩터링")
    return (
        _executor_target_from_message(message) == "hermes"
        and any(term in lowered for term in team_terms)
        and any(term in lowered for term in coding_terms)
    )


def _delegation_is_coding_status_request(delegation_payload: dict[str, object]) -> bool:
    route_context = _nested(delegation_payload, "route_context")
    if route_context.get("coding_status_request"):
        return True
    for recommendation in delegation_payload.get("recommendations", []):
        if not isinstance(recommendation, dict):
            continue
        matched = {str(item) for item in recommendation.get("matched", []) if str(item)}
        if "trigger:session" in matched and {"trigger:codex", "trigger:claude", "trigger:coding"} & matched:
            return True
    return False


def _plan_has_coding_delegate(plan_payload: dict[str, object]) -> bool:
    coding_delegate = _nested(_nested(plan_payload, "wrapper_contract"), "coding_delegate")
    return bool(coding_delegate.get("available", False))


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


def _operating_brief_chat_response(
    *,
    selected: str,
    policy_next_action: str,
    policy: dict[str, object],
    decision: dict[str, object],
    action: str,
    thread_key: str,
    workflow_explanation_reason: str,
) -> dict[str, object] | None:
    workflow = selected if selected in _OPERATING_BRIEF_CHAT_CARDS else _OPERATING_BRIEF_WORKFLOW_BY_NEXT_ACTION.get(policy_next_action, "")
    if not workflow:
        return None
    config = _OPERATING_BRIEF_CHAT_CARDS[workflow]
    next_action = str(config["next_action"])
    action_specs = config.get("actions", [])
    actions = [_action_from_spec(spec) for spec in action_specs if isinstance(spec, dict)]
    evidence_boundary = str(policy.get("evidence_boundary", "")) or "This prepared operating card is not observed work evidence."
    return _chat_response(
        kind=str(config["kind"]),
        headline=str(config["headline"]),
        body=str(config["body"]),
        phase=str(config["phase"]),
        next_action=next_action,
        thread_key=thread_key,
        actions=actions,
        claim_boundary=evidence_boundary,
        extra_state={
            "route_action": action,
            "confidence": decision.get("confidence", "low"),
            "selected_workflow": workflow,
            "workflow_explanation_reason": workflow_explanation_reason,
            "policy_next_action": policy_next_action,
            "artifact_schema": str(config["artifact_schema"]),
            "recommended_flow": list(config.get("recommended_flow", [])),
            "evidence_not_observed": list(config.get("evidence_not_observed", [])),
        },
    )


def _review_quality_chat_response(
    *,
    selected: str,
    policy_next_action: str,
    policy: dict[str, object],
    decision: dict[str, object],
    action: str,
    thread_key: str,
    workflow_explanation_reason: str,
) -> dict[str, object] | None:
    if selected not in _REVIEW_QUALITY_CHAT_CARDS:
        return None
    config = _REVIEW_QUALITY_CHAT_CARDS[selected]
    next_action = str(config["next_action"])
    action_specs = config.get("actions", [])
    actions = [_action_from_spec(spec) for spec in action_specs if isinstance(spec, dict)]
    evidence_boundary = str(policy.get("evidence_boundary", "")) or "This prepared review card is not observed review evidence."
    claim_boundary_suffix = str(config.get("claim_boundary_suffix", "")).strip()
    if claim_boundary_suffix and claim_boundary_suffix.lower() not in evidence_boundary.lower():
        evidence_boundary = f"{evidence_boundary} {claim_boundary_suffix}".strip()
    return _chat_response(
        kind=str(config["kind"]),
        headline=str(config["headline"]),
        body=str(config["body"]),
        phase=str(config["phase"]),
        next_action=next_action,
        thread_key=thread_key,
        actions=actions,
        claim_boundary=evidence_boundary,
        extra_state={
            "route_action": action,
            "confidence": decision.get("confidence", "low"),
            "selected_workflow": selected,
            "workflow_explanation_reason": workflow_explanation_reason,
            "policy_next_action": policy_next_action,
            "artifact_schema": str(config["artifact_schema"]),
            "recommended_flow": list(config.get("recommended_flow", [])),
            "evidence_not_observed": list(config.get("evidence_not_observed", [])),
        },
    )


def _delivery_runtime_chat_response(
    *,
    selected: str,
    policy_next_action: str,
    policy: dict[str, object],
    decision: dict[str, object],
    action: str,
    thread_key: str,
    workflow_explanation_reason: str,
) -> dict[str, object] | None:
    if selected not in _DELIVERY_RUNTIME_CHAT_CARDS:
        return None
    config = _DELIVERY_RUNTIME_CHAT_CARDS[selected]
    next_action = str(config["next_action"])
    action_specs = config.get("actions", [])
    actions = [_action_from_spec(spec) for spec in action_specs if isinstance(spec, dict)]
    evidence_boundary = str(policy.get("evidence_boundary", "")) or "This prepared delivery/runtime card is not observed execution evidence."
    if "execution" not in evidence_boundary.lower():
        evidence_boundary = f"{evidence_boundary} It is not execution evidence.".strip()
    return _chat_response(
        kind=str(config["kind"]),
        headline=str(config["headline"]),
        body=str(config["body"]),
        phase=str(config["phase"]),
        next_action=next_action,
        thread_key=thread_key,
        actions=actions,
        claim_boundary=evidence_boundary,
        extra_state={
            "route_action": action,
            "confidence": decision.get("confidence", "low"),
            "selected_workflow": selected,
            "workflow_explanation_reason": workflow_explanation_reason,
            "policy_next_action": policy_next_action,
            "artifact_schema": str(config["artifact_schema"]),
            "recommended_flow": list(config.get("recommended_flow", [])),
            "evidence_not_observed": list(config.get("evidence_not_observed", [])),
        },
    )


def _workflow_operations_chat_response(
    *,
    selected: str,
    policy_next_action: str,
    policy: dict[str, object],
    decision: dict[str, object],
    action: str,
    thread_key: str,
    workflow_explanation_reason: str,
) -> dict[str, object] | None:
    if selected not in _WORKFLOW_OPERATIONS_CHAT_CARDS:
        return None
    config = _WORKFLOW_OPERATIONS_CHAT_CARDS[selected]
    next_action = str(config["next_action"])
    action_specs = config.get("actions", [])
    actions = [_action_from_spec(spec) for spec in action_specs if isinstance(spec, dict)]
    evidence_boundary = str(policy.get("evidence_boundary", "")) or "This prepared workflow operations card is not observed work evidence."
    claim_boundary_suffix = str(config.get("claim_boundary_suffix", "")).strip()
    if claim_boundary_suffix and claim_boundary_suffix.lower() not in evidence_boundary.lower():
        evidence_boundary = f"{evidence_boundary} {claim_boundary_suffix}".strip()
    return _chat_response(
        kind=str(config["kind"]),
        headline=str(config["headline"]),
        body=str(config["body"]),
        phase=str(config["phase"]),
        next_action=next_action,
        thread_key=thread_key,
        actions=actions,
        claim_boundary=evidence_boundary,
        extra_state={
            "route_action": action,
            "confidence": decision.get("confidence", "low"),
            "selected_workflow": selected,
            "workflow_explanation_reason": workflow_explanation_reason,
            "policy_next_action": policy_next_action,
            "artifact_schema": str(config["artifact_schema"]),
            "recommended_flow": list(config.get("recommended_flow", [])),
            "evidence_not_observed": list(config.get("evidence_not_observed", [])),
        },
    )


def build_chat_response_from_route(
    decision: dict[str, object],
    *,
    thread_key: str = "",
    message: str = "",
    include_message: bool = False,
) -> dict[str, object]:
    action = str(decision.get("action", "fallback"))
    copy_locale = detect_copy_locale(message)
    localized_copy = is_localized_locale(copy_locale)
    if _is_command_preview_invocation(message):
        return _command_preview_response(decision, thread_key=thread_key, message=message)
    if (
        str(decision.get("selected_skill", "")) == _ROUTER_SKILL
        and _route_recommendation_next_action(decision) == "show_command_preview"
    ):
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
        learning_candidate_card = decision.get("learning_candidate_card")
        if isinstance(learning_candidate_card, dict) and learning_candidate_card:
            return _chat_response_from_learning_candidate_card(
                learning_candidate_card,
                decision=decision,
                thread_key=thread_key,
                workflow_explanation_reason=workflow_explanation_reason,
            )
        if selected == "feedback-triage" or policy_next_action == "triage_feedback":
            evidence_boundary = str(policy.get("evidence_boundary", "")) or "Feedback triage is not implementation evidence."
            body = (
                "I will treat this as a customer or product signal first: cluster reports, separate bug, request, "
                "and question paths, name severity and affected surface, then prepare investigation and reproduction "
                "questions. A coding handoff only follows after the signal is classified and reproduction or acceptance "
                "evidence exists."
            )
            return _chat_response(
                kind="feedback_triage",
                headline="I can triage this signal before anyone codes.",
                body=body,
                phase="feedback_triage_prepared",
                next_action="triage_feedback",
                thread_key=thread_key,
                actions=[
                    _action("triage_feedback", "Triage signal", "primary"),
                    _action(
                        "prepare_coding_handoff",
                        "Prepare fix handoff",
                        "secondary",
                        enabled=False,
                        payload={"requires": "classified bug/request/question path and reproduction or acceptance evidence"},
                    ),
                    _action("prepare_report_package", "Prepare triage report", "secondary"),
                    _action("show_status", "Show status", "secondary"),
                ],
                claim_boundary=evidence_boundary,
                extra_state={
                    "route_action": action,
                    "confidence": decision.get("confidence", "low"),
                    "selected_workflow": selected,
                    "workflow_explanation_reason": workflow_explanation_reason,
                    "policy_next_action": policy_next_action,
                    "artifact_schema": "feedback_triage_card/v1",
                    "recommended_flow": [
                        "cluster_signal",
                        "classify_bug_request_question",
                        "prepare_investigation_or_repro_plan",
                        "prepare_coding_handoff_if_needed",
                    ],
                    "evidence_not_observed": [
                        "completed feedback triage",
                        "observed customer examples",
                        "severity confirmation",
                        "reproduction evidence",
                        "coding handoff",
                        "fix implementation",
                        "root cause",
                        "roadmap decision",
                        "verification",
                    ],
                },
            )
        operating_brief_response = _operating_brief_chat_response(
            selected=selected,
            policy_next_action=policy_next_action,
            policy=policy,
            decision=decision,
            action=action,
            thread_key=thread_key,
            workflow_explanation_reason=workflow_explanation_reason,
        )
        if operating_brief_response:
            return operating_brief_response
        review_quality_response = _review_quality_chat_response(
            selected=selected,
            policy_next_action=policy_next_action,
            policy=policy,
            decision=decision,
            action=action,
            thread_key=thread_key,
            workflow_explanation_reason=workflow_explanation_reason,
        )
        if review_quality_response:
            return review_quality_response
        delivery_runtime_response = _delivery_runtime_chat_response(
            selected=selected,
            policy_next_action=policy_next_action,
            policy=policy,
            decision=decision,
            action=action,
            thread_key=thread_key,
            workflow_explanation_reason=workflow_explanation_reason,
        )
        if delivery_runtime_response:
            return delivery_runtime_response
        workflow_operations_response = _workflow_operations_chat_response(
            selected=selected,
            policy_next_action=policy_next_action,
            policy=policy,
            decision=decision,
            action=action,
            thread_key=thread_key,
            workflow_explanation_reason=workflow_explanation_reason,
        )
        if workflow_operations_response:
            return workflow_operations_response
        if selected == "loop" or policy_next_action == "start_goal_loop":
            evidence_boundary = str(policy.get("evidence_boundary", "")) or "A goal loop is orchestration state only."
            body = str(policy.get("wrapper_guidance", "")) or (
                "Start the loop and keep moving through interviewer, planner, builder, reviewer, and next-loop gates while keeping observed evidence separate."
            )
            loop_start_card = build_loop_start_card(
                message or selected,
                include_goal=include_message,
                source=str(decision.get("source", "generic")),
            )
            assessment = loop_start_card.get("loopability_assessment", {})
            loop_next_action = str(loop_start_card.get("next_action") or assessment.get("recommended_next_action", "start_goal_loop"))
            loopability = str(assessment.get("loopability", "loopable"))
            loop_invocation = _nested(loop_start_card, "loop_invocation")
            explicit_loop = loop_invocation.get("invoked") is True
            if explicit_loop and loop_next_action == "start_loop_cycle":
                headline = "Loop started; I will keep going until a real gate."
                body = (
                    "I will advance through interviewer, planner, researcher, builder, reviewer, and loop-controller lanes; "
                    "prepared steps stay separate from observed execution, review, CI, merge, or publication evidence."
                )
                primary_action = "start_loop"
            elif loopability == "needs_clarification":
                headline = "This needs a loop goal clarification."
                body = "I need a bounded arena, observable problem, next verification, or stop condition before a loop can start."
                primary_action = "assess_loopability"
            elif loopability == "direct_task":
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
            if primary_action != "start_loop":
                loop_actions.append(
                    _action(
                        "start_loop",
                        "Start loop",
                        "primary",
                        enabled=loopability == "loopable" or (explicit_loop and loop_next_action == "start_loop_cycle"),
                    )
                )
            loop_actions.extend(
                [
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
                    "loop_invocation": loop_invocation,
                    "role_pipeline": loop_start_card.get("role_pipeline", []),
                    "core_skills": loop_start_card.get("core_skills", []),
                    "loopability_assessment": assessment,
                    "permission_profile_required": bool(loop_start_card.get("permission_profile_required", True)),
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
        if selected == "ultraprocess" and _route_is_coding_status_request(decision):
            evidence_boundary = str(policy.get("evidence_boundary", "")) or "Coding-agent status is observed only after runtime evidence is recorded."
            body = (
                "I can show the coding-agent status card and explain which handoff, dispatch, result, verification, review, CI, "
                "or merge evidence is still missing. If no executor session is attached yet, I will not invent progress."
            )
            return _chat_response(
                kind="handoff",
                headline="I can show the coding-agent status for this work.",
                body=body,
                phase="handoff_status",
                next_action="show_coding_handoff_status",
                thread_key=thread_key,
                actions=[
                    _action("show_coding_handoff_status", "Show coding status", "primary"),
                    _action("attach_executor_session", "Attach executor session", "secondary", enabled=False),
                    _action("choose_executor", "Choose coding agent", "secondary"),
                    _action("show_status", "Show status", "secondary"),
                ],
                claim_boundary=evidence_boundary,
                extra_state={
                    "route_action": action,
                    "confidence": decision.get("confidence", "low"),
                    "selected_workflow": selected,
                    "workflow_explanation_reason": workflow_explanation_reason,
                    "policy_next_action": policy_next_action,
                    "coding_status_request": True,
                    "handoff_status": "prepared_not_observed",
                    "evidence_not_observed": [
                        "executor/runtime dispatch",
                        "executor session attachment",
                        "implementation result",
                        "verification",
                        "review",
                        "CI",
                        "merge readiness",
                        "merge",
                    ],
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
            copy = chat_copy("img_summary", locale=copy_locale)
            return _chat_response(
                kind="img_summary",
                headline=copy.headline,
                body=copy.body,
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
        if selected == "paper-learning" or policy_next_action == "prepare_paper_learning":
            evidence_boundary = str(policy.get("evidence_boundary", "")) or "A paper-learning card is not paper validation evidence."
            copy = chat_copy("paper_learning", locale=copy_locale)
            return _chat_response(
                kind="paper_learning",
                headline=copy.headline,
                body=copy.body,
                phase="paper_learning_prepared",
                next_action="prepare_paper_learning",
                thread_key=thread_key,
                actions=[
                    _action("choose_explanation_level", "Choose level", "primary"),
                    _action("show_paper_source_requirements", "Show source needs", "secondary"),
                    _action("record_paper_metadata", "Record metadata", "secondary"),
                    _action("record_paper_excerpt_observed", "Record excerpt", "secondary"),
                    _action("record_file_text_extraction_observed", "Record text extraction", "secondary"),
                    _action("show_paper_learning", "Show paper learning", "secondary"),
                    _action("continue_next_section", "Next section", "secondary"),
                    _action("revise_explanation_level", "Revise level", "secondary"),
                    _action("show_coverage_ledger", "Coverage ledger", "secondary"),
                    _action("record_user_review", "Record user review", "secondary"),
                    _action("show_status", "Show status", "secondary"),
                ],
                claim_boundary=evidence_boundary,
                extra_state={
                    "route_action": action,
                    "confidence": decision.get("confidence", "low"),
                    "selected_workflow": selected,
                    "workflow_explanation_reason": workflow_explanation_reason,
                    "policy_next_action": policy_next_action,
                    "artifact_schema": "paper_learning_card/v1",
                    "source_state_schema": "paper_source_state/v1",
                    "coverage_ledger_schema": "paper_coverage_ledger/v1",
                    "default_level": "choose",
                    "evidence_not_observed": [
                        "full PDF extraction",
                        "figure OCR",
                        "external citation checking",
                        "math validation",
                        "code reproduction",
                        "peer review",
                        "proof that paper claims are true",
                    ],
                },
            )
        if selected == "source-finder" or policy_next_action == "prepare_source_finder_plan":
            evidence_boundary = str(policy.get("evidence_boundary", "")) or "A source-finder plan is not source retrieval evidence."
            copy = chat_copy("source_finder", locale=copy_locale)
            return _chat_response(
                kind="source_finder",
                headline=copy.headline,
                body=copy.body,
                phase="source_finder_prepared",
                next_action="prepare_source_finder_plan",
                thread_key=thread_key,
                actions=[
                    _action("show_source_candidates", "Show candidates", "primary"),
                    _action("record_source_candidate", "Record candidate", "secondary"),
                    _action("record_source_link_observed", "Record source link", "secondary"),
                    _action("record_download_observed", "Record download", "secondary"),
                    _action("record_file_hash", "Record file hash", "secondary"),
                    _action("record_text_extraction_observed", "Record text extraction", "secondary"),
                    _action("record_license_check", "Record license check", "secondary"),
                    _action("choose_source", "Choose source", "secondary"),
                    _action("route_to_downstream_workflow", "Route downstream", "secondary"),
                    _action("show_acquisition_status", "Show acquisition status", "secondary"),
                    _action("show_status", "Show status", "secondary"),
                ],
                claim_boundary=evidence_boundary,
                extra_state={
                    "route_action": action,
                    "confidence": decision.get("confidence", "low"),
                    "selected_workflow": selected,
                    "workflow_explanation_reason": workflow_explanation_reason,
                    "policy_next_action": policy_next_action,
                    "artifact_schema": "source_finder_plan/v1",
                    "candidate_schema": "source_candidate_set/v1",
                    "acquisition_status_schema": "source_acquisition_status/v1",
                    "downstream_workflow_required": True,
                    "evidence_not_observed": [
                        "web search",
                        "download",
                        "repository clone",
                        "file extraction",
                        "file hash verification",
                        "license verification",
                        "source correctness verification",
                        "downstream processing",
                    ],
                },
            )
        if selected == "web-research" or policy_next_action == "run_hermes_research":
            evidence_boundary = str(policy.get("evidence_boundary", "")) or "A web research card is not source retrieval evidence."
            copy = chat_copy("web_research", locale=copy_locale)
            return _chat_response(
                kind="web_research",
                headline=copy.headline,
                body=copy.body,
                phase="web_research_prepared",
                next_action="run_hermes_research",
                thread_key=thread_key,
                actions=[
                    _action("run_hermes_research", "Start research", "primary"),
                    _action("record_source_observation", "Record source observation", "secondary"),
                    _action("prepare_source_finder_plan", "Prepare source finder", "secondary"),
                    _action("prepare_research_department_plan", "Prepare research ops", "secondary"),
                    _action("prepare_report_package", "Prepare report", "secondary"),
                    _action("show_status", "Show status", "secondary"),
                ],
                claim_boundary=evidence_boundary,
                extra_state={
                    "route_action": action,
                    "confidence": decision.get("confidence", "low"),
                    "selected_workflow": selected,
                    "workflow_explanation_reason": workflow_explanation_reason,
                    "policy_next_action": policy_next_action,
                    "artifact_schema": "web_research_brief/v1",
                    "observation_schema": "source_observation/v1",
                    "research_scope": "source_backed_current_evidence",
                    "evidence_not_observed": [
                        "source retrieval",
                        "source access",
                        "citation verification",
                        "source diversity",
                        "freshness confirmation",
                        "downstream plan or handoff",
                    ],
                },
            )
        if selected == "doctor" or policy_next_action == "run_local_operator_check":
            evidence_boundary = str(policy.get("evidence_boundary", "")) or (
                "A local operator check is health evidence only after the check runs; it is not Hermes reload, "
                "plugin-load, executor dispatch, implementation, review, CI, or merge evidence."
            )
            body = (
                "I will check the local OMH install path: command availability, managed workflows, runtime state, "
                "Hermes registration, target detection, plugin surface, and the next repair step if something is stale. "
                "This keeps setup/update questions in the operator health lane instead of asking for shell approval first."
            )
            return _chat_response(
                kind="doctor_health",
                headline="I can check whether OMH is installed and connected correctly.",
                body=body,
                phase="doctor_health_prepared",
                next_action="run_local_operator_check",
                thread_key=thread_key,
                actions=[
                    _action("run_local_operator_check", "Run local check", "primary"),
                    _action("run_omh_doctor", "Run omh doctor", "secondary"),
                    _action("run_omh_setup", "Repair setup", "secondary"),
                    _action("run_omh_update", "Refresh workflows", "secondary"),
                    _action("show_status", "Show status", "secondary"),
                ],
                claim_boundary=evidence_boundary,
                extra_state={
                    "route_action": action,
                    "confidence": decision.get("confidence", "low"),
                    "selected_workflow": selected,
                    "workflow_explanation_reason": workflow_explanation_reason,
                    "policy_next_action": policy_next_action,
                    "artifact_schema": "doctor_health_card/v1",
                    "local_operator_check": True,
                    "evidence_not_observed": [
                        "command availability",
                        "workflow installation health",
                        "Hermes registration reload",
                        "plugin runtime load",
                        "executor dispatch",
                        "implementation",
                        "review",
                        "CI",
                        "merge",
                    ],
                },
            )
        if selected == "agent-ops-review" or policy_next_action == "prepare_agent_ops_review":
            evidence_boundary = str(policy.get("evidence_boundary", "")) or "An agent ops review card is not runtime evidence."
            card = build_agent_operator_productivity_card(
                message or selected,
                source=str(decision.get("source", "generic")),
            )
            status_card = card["status_card"]
            copy = chat_copy("agent_ops_review", locale=copy_locale)
            headline = copy.headline if localized_copy else str(status_card.get("headline", copy.headline))
            return _chat_response(
                kind="agent_ops_review",
                headline=headline,
                body=copy.body,
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
            copy = chat_copy(
                "workflow_learning_missed_route" if missed_route_feedback else "workflow_learning_readiness",
                locale=copy_locale,
            )
            evidence_boundary = str(policy.get("evidence_boundary", "")) or (
                "Workflow learning records are process-review evidence only; they are not automatic improvement evidence."
            )
            return _chat_response(
                kind="workflow_learning",
                headline=copy.headline,
                body=copy.body,
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
        copy = chat_copy("clarify", locale=copy_locale)
        body = copy.body if localized_copy else str(decision.get("clarification") or copy.body)
        return _chat_response(
            kind="clarification",
            headline=copy.headline,
            body=body,
            phase="clarifying",
            next_action="answer_clarification",
            thread_key=thread_key,
            actions=[_action("answer:clarify", "Answer clarification", "primary"), _action("cancel", "Cancel", "secondary")],
            claim_boundary="No execution has started.",
            extra_state={"route_action": action, "confidence": decision.get("confidence", "low")},
        )
    if action == "fallback" and _is_file_lookup_fallback(decision):
        copy = chat_copy("file_lookup", locale=copy_locale)
        body = copy.body if localized_copy else str(decision.get("clarification") or copy.body)
        return _chat_response(
            kind="clarification",
            headline=copy.headline,
            body=body,
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
    if action == "fallback" and _is_direct_answer_fallback(decision):
        copy = chat_copy("direct_answer", locale=copy_locale)
        body = copy.body if localized_copy else str(decision.get("clarification") or copy.body)
        return _chat_response(
            kind="clarification",
            headline=copy.headline,
            body=body,
            phase="clarifying",
            next_action="answer_directly",
            thread_key=thread_key,
            actions=[
                _action("answer:direct", "Answer directly", "primary"),
                _action("cancel", "Cancel", "secondary"),
            ],
            claim_boundary="No OMH workflow, picker, handoff, execution, or file inspection has started.",
            extra_state={
                "route_action": action,
                "confidence": decision.get("confidence", "low"),
                "lookup_kind": "direct_answer",
                "routing_instruction": decision.get("routing_instruction", ""),
            },
        )
    copy = chat_copy("generic_clarify", locale=copy_locale)
    return _chat_response(
        kind="clarification",
        headline=copy.headline,
        body=copy.body,
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


def _is_direct_answer_fallback(decision: dict[str, object]) -> bool:
    text = " ".join(
        str(decision.get(key, "") or "")
        for key in ("reason", "clarification", "routing_instruction")
    ).lower()
    return "answer directly" in text and "omh workflow" in text


def _route_task_card(decision: dict[str, object]) -> dict[str, object]:
    task_card = decision.get("task_card")
    return dict(task_card) if isinstance(task_card, dict) else {}


def _task_card_state(decision: dict[str, object]) -> dict[str, object]:
    task_card = _route_task_card(decision)
    return {"task_card": task_card} if task_card else {}


def _chat_response_from_learning_candidate_card(
    card: dict[str, object],
    *,
    decision: dict[str, object],
    thread_key: str,
    workflow_explanation_reason: str,
) -> dict[str, object]:
    target = str(card.get("persistence_target", "review_first"))
    primary_action = str(card.get("primary_action", "show_learning_candidate"))
    summary = str(card.get("summary", "")).strip()
    prompt = card.get("learn_prompt")
    has_prompt = isinstance(prompt, dict) and bool(prompt.get("copy_text"))
    if target == "skill_candidate":
        headline = "I can prepare this for Hermes /learn."
        body = (
            "This is a reusable skill candidate. I prepared a sanitized copy-ready /learn prompt for Hermes Agent; "
            "OMH has not run /learn, created a skill, or changed memory. "
            f"Candidate: {summary}"
        )
    elif target == "memory_candidate":
        headline = "I can queue this as a memory candidate."
        body = (
            "This looks like a durable user preference, so it should go through memory curation review before anything is saved. "
            f"Candidate: {summary}"
        )
    elif target == "session_only":
        headline = "This should stay session-only."
        body = (
            "The request points at transient task, PR, run, process, branch, or channel state. I will show it as a learning signal "
            "without preparing persistence. "
            f"Candidate: {summary}"
        )
    else:
        headline = "This learning request needs review first."
        body = (
            "The request is ambiguous, conflicting, or cross-channel. Route it through memory curation review before persistence. "
            f"Candidate: {summary}"
        )

    actions: list[dict[str, object]] = []
    if has_prompt:
        actions.append(_action("copy_learn_prompt", "Copy /learn prompt", "primary", payload=prompt))
    actions.append(_action("show_learning_candidate", "Show candidate", "primary" if not actions else "secondary", payload=card))
    if target in {"memory_candidate", "review_first"}:
        actions.append(_action("prepare_memory_curation_review", "Review memory", "primary" if not has_prompt else "secondary", payload=card))
        actions.append(_action("show_memory_status", "Show memory status", "secondary"))
    actions.append(_action("show_status", "Show status", "secondary"))

    return _chat_response(
        kind="learning_candidate",
        headline=headline,
        body=body,
        phase="learning_candidate_prepared",
        next_action=primary_action,
        thread_key=thread_key,
        actions=actions,
        claim_boundary=str(card.get("claim_boundary", "Learning candidate is prepared_not_observed.")),
        extra_state={
            "route_action": decision.get("action", "dispatch"),
            "confidence": decision.get("confidence", "high"),
            "selected_workflow": card.get("recommended_workflow", decision.get("selected_skill", "")),
            "workflow_explanation_reason": workflow_explanation_reason,
            "learning_candidate_card_schema": card.get("schema_version", ""),
            "learning_candidate_target": target,
            "learning_candidate_status": card.get("status", "prepared_not_observed"),
            "primary_learning_action": primary_action,
            "learning_candidate_card": card,
            "scope": card.get("scope", {}),
            "artifact_schemas": ["learning_candidate_card/v1", "hermes_learn_prompt/v1"],
            "evidence_not_observed": card.get("not_observed", []),
        },
    )


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
    summary = str(task_card.get("user_facing_summary", "")).strip()
    not_a_workflow = _string_items(task_card.get("not_a_workflow", []))
    secret_action = str(secret_policy.get("recommended_action", "")).strip()
    invariant = str(gateway_transfer.get("invariant", "")).strip().replace("_", " ")

    body_lines = [
        summary or f"This is a {task_type} task.",
        f"Not a workflow: {', '.join(_display_items(not_a_workflow[:5]))}." if not_a_workflow else "",
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


def _open_coding_agent_label(profile: str | None) -> str:
    if profile == "codex":
        return "Open in Codex"
    if profile == "claude-code":
        return "Open in Claude Code"
    if profile == "hermes":
        return "Open Hermes coding"
    if profile:
        return f"Open {executor_label(profile)}"
    return "Open coding agent"


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
        if coding_delegate.get("executor_choice_required"):
            actions.append(_action("choose_executor", "Choose coding agent", "secondary"))
        actions.append(_action("prepare_handoff", "Prepare handoff", "secondary", enabled=False))
    selected = str(plan.get("recommended_workflow", "plan"))
    executor_resolution = _nested(coding_delegate, "executor_resolution")
    selected_executor = coding_delegate.get("selected_executor_profile")
    executor_choice_required = bool(coding_delegate.get("executor_choice_required", False))
    next_copy = (
        "Accept or revise the plan first; choose the executor before handoff if needed."
        if executor_choice_required
        else "Accept or revise the plan first; the handoff button stays disabled until acceptance."
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
            "executor_choice_required": executor_choice_required,
            "selected_executor_profile": selected_executor,
            "work_owner_mode": coding_delegate.get("work_owner_mode", ""),
            "executor_resolution": executor_resolution,
            "prepared_handoff_field": coding_delegate.get("prepared_handoff_field", ""),
            "prepared_handoff_boundary": coding_delegate.get("prepared_handoff_boundary", ""),
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
    executor_resolution = _nested(delegation_payload, "executor_resolution")
    action = str(delegation.get("action", "fallback"))
    if action == "delegate" and delegation_payload.get("executor_handoff"):
        handoff = _nested(delegation_payload, "executor_handoff")
        executor = str(handoff.get("selected_executor_profile") or handoff.get("executor_target") or "executor")
        label = executor_label(executor)
        status_request = _delegation_is_coding_status_request(delegation_payload)
        actions = []
        if status_request:
            actions.append(_action("show_coding_handoff_status", "Show coding status", "primary"))
        actions.append(
            _action(
                "send_to_executor",
                _open_coding_agent_label(executor),
                "secondary" if status_request else "primary",
                payload={"selected_executor_profile": executor},
            )
        )
        if executor == "codex":
            actions.append(_action("send_to_codex", "Open in Codex", "secondary", payload={"compatibility_alias": True}))
        if status_request:
            actions.append(
                _action(
                    "attach_executor_session",
                    f"Attach existing {label} session",
                    "secondary",
                    enabled=False,
                    payload={
                        "selected_executor_profile": executor,
                        "disabled_reason": "A wrapper session id is required before OMH can attach observed coding-session evidence.",
                    },
                )
            )
        actions.append(_action("show_status", "Show status", "secondary"))
        return _chat_response(
            kind="handoff",
            headline=(
                f"{label} is selected; session evidence is not attached yet."
                if status_request
                else "A coding-agent handoff is ready."
            ),
            body=(
                f"I can open {label} with the prepared handoff or attach an existing {label} session. "
                "Until wrapper evidence records dispatch, progress, result, or verification, I cannot say what the coding agent has done."
                if status_request
                else f"I can open {label} with this prepared handoff, but I will not claim implementation until coding-agent evidence is observed."
            ),
            phase="handoff_prepared",
            next_action="show_coding_handoff_status" if status_request else "send_to_executor",
            thread_key=thread_key,
            actions=actions,
            claim_boundary="Prepared handoff is not execution evidence.",
            extra_state={
                "delegation_action": action,
                "intent": delegation.get("intent", "unknown"),
                "selected_workflow": delegation.get("recommended_workflow", ""),
                "work_owner_mode": delegation_payload.get("work_owner_mode", "external_executor"),
                "selected_executor_profile": delegation_payload.get("selected_executor_profile", "codex"),
                "executor_choice_required": False,
                "dispatch_policy": delegation_payload.get("dispatch_policy", "ask_before_dispatch"),
                "executor_target": handoff.get("executor_target", "codex"),
                "handoff_status": handoff.get("status", "prepared_not_observed"),
                "prepared_handoff_boundary": "Prepared handoff is not execution evidence.",
                "executor_readiness": delegation_payload.get("executor_readiness", {}),
                "executor_resolution": executor_resolution,
                "coding_status_request": status_request,
                "route_context": delegation_payload.get("route_context", {}),
            },
        )
    if action == "delegate" and delegation_payload.get("prompt_handoff"):
        prompt_handoff = _nested(delegation_payload, "prompt_handoff")
        selected = str(prompt_handoff.get("selected_executor_profile") or "executor")
        label = executor_label(selected)
        status_request = _delegation_is_coding_status_request(delegation_payload)
        actions = []
        if status_request:
            actions.append(_action("show_coding_handoff_status", "Show coding status", "primary"))
        actions.extend(
            [
                _action(
                    "show_prompt_handoff",
                    f"Show {label} prompt",
                    "secondary" if status_request else "primary",
                    payload={"selected_executor_profile": selected},
                ),
                _action("copy_prompt_handoff", f"Copy {label} prompt", "secondary", payload={"selected_executor_profile": selected}),
            ]
        )
        actions.append(_action("choose_executor", "Change coding agent", "secondary"))
        if status_request:
            actions.append(
                _action(
                    "attach_executor_session",
                    f"Attach existing {label} session",
                    "secondary",
                    enabled=False,
                    payload={
                        "selected_executor_profile": selected,
                        "disabled_reason": "A wrapper session id is required before OMH can attach observed coding-session evidence.",
                    },
                )
            )
        actions.append(_action("show_status", "Show status", "secondary"))
        return _chat_response(
            kind="handoff",
            headline=(
                f"{label} is selected; session evidence is not attached yet."
                if status_request
                else "A prompt handoff is ready."
            ),
            body=(
                f"I can show or copy the {label} prompt, then the wrapper can attach an observed {label} session. "
                "Until dispatch, progress, result, or verification evidence is recorded, I cannot say what the coding agent has done."
                if status_request
                else f"I prepared a copyable {selected} prompt. This is not dispatch, execution, review, CI, or merge evidence."
            ),
            phase="prompt_handoff_prepared",
            next_action="show_coding_handoff_status" if status_request else "show_prompt_handoff",
            thread_key=thread_key,
            actions=actions,
            claim_boundary="Prompt handoff is prepared only; OMH has not dispatched it to an executor.",
            extra_state={
                "delegation_action": action,
                "intent": delegation.get("intent", "unknown"),
                "selected_workflow": delegation.get("recommended_workflow", ""),
                "work_owner_mode": "prompt_only_handoff",
                "selected_executor_profile": selected,
                "executor_choice_required": False,
                "dispatch_policy": "prepare_only",
                "dispatchable": False,
                "handoff_status": prompt_handoff.get("status", "prepared_not_observed"),
                "prepared_handoff_boundary": "Prompt handoff is prepared only; OMH has not dispatched it to an executor.",
                "executor_readiness": delegation_payload.get("executor_readiness", {}),
                "executor_resolution": executor_resolution,
                "coding_status_request": status_request,
                "route_context": delegation_payload.get("route_context", {}),
            },
        )
    if action == "delegate" and delegation_payload.get("runtime_handoff"):
        runtime_handoff = _nested(delegation_payload, "runtime_handoff")
        selected = str(runtime_handoff.get("selected_executor_profile") or "runtime")
        runtime_profile = _nested(runtime_handoff, "runtime_profile")
        runtime_label = str(runtime_profile.get("label") or executor_label(selected))
        status_request = _delegation_is_coding_status_request(delegation_payload)
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
            next_action="show_coding_handoff_status" if status_request else "show_runtime_handoff",
            thread_key=thread_key,
            actions=[
                *([_action("show_coding_handoff_status", "Show coding status", "primary")] if status_request else []),
                _action(
                    "show_runtime_handoff",
                    "Show runtime",
                    "secondary" if status_request else "primary",
                    payload={"selected_executor_profile": selected},
                ),
                *extra_actions,
                _action(primary_action, primary_label, "primary", enabled=False, payload={"selected_executor_profile": selected}),
                _action("prepare_worktree", "Prepare worktree", "secondary", enabled=False, payload={"selected_executor_profile": selected}),
                _action("start_team", "Start team", "secondary", enabled=False, payload={"selected_executor_profile": selected}),
                _action("start_swarm", "Start swarm", "secondary", enabled=False, payload={"selected_executor_profile": selected}),
                _action("choose_executor", "Change coding agent", "secondary"),
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
                "selected_workflow": delegation.get("recommended_workflow", ""),
                "work_owner_mode": "runtime_handoff",
                "selected_executor_profile": selected,
                "executor_choice_required": False,
                "runtime_family": runtime_profile.get("runtime_family", ""),
                "underlying_agent": runtime_profile.get("underlying_agent", ""),
                "dispatch_policy": "prepare_only",
                "dispatchable": False,
                "handoff_status": runtime_handoff.get("status", "prepared_not_observed"),
                "prepared_handoff_boundary": (
                    hermes_coding_team_claim_boundary()
                    if selected == "hermes"
                    else "Runtime handoff is prepared only; OMH has not started Hermes, OMX, OMO, OMC, workers, tmux, or worktrees."
                ),
                "executor_readiness": delegation_payload.get("executor_readiness", {}),
                "executor_resolution": executor_resolution,
                "coding_status_request": status_request,
            },
        )
    if action == "delegate" and _nested(delegation_payload, "executor_selection").get("choice_required"):
        return _chat_response(
            kind="handoff",
            headline="Choose the coding agent.",
            body="Pick Codex, Claude Code, Hermes, or an oh-my runtime path before this becomes a prepared coding handoff.",
            phase="executor_choice_required",
            next_action="choose_executor",
            thread_key=thread_key,
            actions=[_action("choose_executor", "Choose coding agent", "primary"), _action("show_status", "Show status", "secondary")],
            claim_boundary="Coding-agent choice is not dispatch or implementation evidence.",
            extra_state={
                "delegation_action": action,
                "intent": delegation.get("intent", "unknown"),
                "selected_workflow": delegation.get("recommended_workflow", ""),
                "work_owner_mode": "external_executor",
                "selected_executor_profile": None,
                "executor_choice_required": True,
                "dispatchable": False,
                "executor_options": _nested(delegation_payload, "executor_selection").get("options", []),
                "prepared_handoff_boundary": "Coding-agent choice is not dispatch or implementation evidence.",
                "executor_readiness": delegation_payload.get("executor_readiness", {}),
                "executor_resolution": executor_resolution,
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
    if next_action == "choose_executor":
        actions.insert(0, _action("choose_executor", "Choose coding agent", "primary"))
    if next_action == "dispatch_to_executor":
        selected = str(_nested(status_payload, "prepared").get("executor_target", "") or _nested(status_payload, "prepared").get("selected_executor_profile", ""))
        actions.insert(0, _action("send_to_executor", _open_coding_agent_label(selected), "primary"))
        if str(_nested(status_payload, "prepared").get("executor_target", "")) == "codex":
            actions.insert(1, _action("send_to_codex", "Open in Codex", "secondary", payload={"compatibility_alias": True}))
    if next_action == "show_prompt_handoff":
        selected = str(_nested(status_payload, "prepared").get("selected_executor_profile", "") or "")
        actions.insert(
            0,
            _action(
                "show_prompt_handoff",
                "Show prompt",
                "primary",
                payload={"selected_executor_profile": selected},
            ),
        )
        actions.insert(
            1,
            _action(
                "copy_prompt_handoff",
                "Copy prompt",
                "secondary",
                payload={"selected_executor_profile": selected},
            ),
        )
    if next_action == "show_runtime_handoff":
        selected = str(_nested(status_payload, "prepared").get("selected_executor_profile", "") or "")
        actions.insert(
            0,
            _action(
                "show_runtime_handoff",
                "Show runtime",
                "primary",
                payload={"selected_executor_profile": selected},
            ),
        )
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
    probe = _omh_status_probe(paths)
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


def _omh_status_probe(paths: OmhPaths) -> dict[str, object]:
    return _clone_static_dict(
        _omh_status_probe_cached(
            str(paths.omh_home),
            str(paths.hermes_home),
            _omh_status_probe_fingerprint(paths),
        )
    )


@lru_cache(maxsize=64)
def _omh_status_probe_cached(
    omh_home: str,
    hermes_home: str,
    _fingerprint: tuple[tuple[str, int, int, int], ...],
) -> dict[str, object]:
    return _omh_status_probe_projection(
        probe_capabilities(OmhPaths(omh_home=Path(omh_home), hermes_home=Path(hermes_home)), include_roadmap=True)
    )


def _omh_status_probe_projection(probe: dict[str, object]) -> dict[str, object]:
    roadmap = probe.get("capability_gap_roadmap")
    return {
        "claim_boundary": probe.get("claim_boundary"),
        "plugin_distribution_ready": bool(probe.get("plugin_distribution_ready")),
        "plugin_runtime_active": bool(probe.get("plugin_runtime_active")),
        "native_integration_claim_ready": bool(probe.get("native_integration_claim_ready")),
        "team_worker_readiness_ready": bool(probe.get("team_worker_readiness_ready")),
        "mcp_host_session_observed": bool(probe.get("mcp_host_session_observed")),
        "capability_gap_roadmap": roadmap if isinstance(roadmap, dict) else {},
    }


def _omh_status_probe_fingerprint(paths: OmhPaths) -> tuple[tuple[str, int, int, int], ...]:
    watched = (
        paths.hermes_config_path,
        paths.skills_dir / "oh-my-hermes" / "SKILL.md",
        paths.runtime_state_path,
        paths.runtime_runs_dir,
        paths.runtime_wrapper_sessions_dir,
        paths.runtime_mcp_host_sessions_path,
        paths.runtime_plugin_host_observations_path,
        paths.runtime_worktrees_path,
        paths.executor_readiness_path,
        paths.target_registry_path,
        paths.hermes_home / "hooks.yaml",
        paths.hermes_home / "hooks.json",
        paths.hermes_home / ".mcp.json",
        paths.hermes_home / "mcp.json",
        paths.hermes_plugins_dir,
        paths.hermes_plugin_dir,
        paths.hermes_plugin_dir / ".omh-plugin-manifest.json",
        paths.hermes_plugin_dir / "plugin.yaml",
        paths.hermes_plugin_dir / "__init__.py",
        paths.hermes_home / "apps",
    )
    run_child_fingerprint = _child_dir_fingerprints(paths.runtime_runs_dir)
    session_child_fingerprint = _child_dir_fingerprints(paths.runtime_wrapper_sessions_dir)
    runtime_files = (
        _glob_fingerprints(
            paths.runtime_runs_dir,
            "*/run.json",
            child_dir_fingerprints=run_child_fingerprint,
        )
        + _glob_fingerprints(
            paths.runtime_runs_dir,
            "*/wrapper.json",
            child_dir_fingerprints=run_child_fingerprint,
        )
        + _glob_fingerprints(
            paths.runtime_runs_dir,
            "*/runtime_observations.jsonl",
            child_dir_fingerprints=run_child_fingerprint,
        )
        + _glob_fingerprints(
            paths.runtime_wrapper_sessions_dir,
            "*/session.json",
            child_dir_fingerprints=session_child_fingerprint,
        )
        + _glob_fingerprints(
            paths.runtime_wrapper_sessions_dir,
            "*/runtime_observations.jsonl",
            child_dir_fingerprints=session_child_fingerprint,
        )
    )
    return tuple(_path_fingerprint(path) for path in watched) + runtime_files


def _glob_fingerprints(
    root: Path,
    pattern: str,
    *,
    child_dir_fingerprints: tuple[tuple[str, int, int, int], ...] | None = None,
    limit: int = 256,
) -> tuple[tuple[str, int, int, int], ...]:
    paths = _glob_fingerprint_paths_cached(
        str(root),
        pattern,
        limit,
        _path_fingerprint(root),
        child_dir_fingerprints if child_dir_fingerprints is not None else _child_dir_fingerprints(root, limit=limit),
    )
    return tuple(_path_fingerprint(Path(path)) for path in paths)


@lru_cache(maxsize=128)
def _glob_fingerprint_paths_cached(
    root: str,
    pattern: str,
    limit: int,
    _root_fingerprint: tuple[str, int, int, int],
    _child_dir_fingerprints: tuple[tuple[str, int, int, int], ...],
) -> tuple[str, ...]:
    try:
        paths = sorted(Path(root).glob(pattern))
    except OSError:
        return ()
    return tuple(str(path) for path in paths[:limit])


def _child_dir_fingerprints(root: Path, *, limit: int = 256) -> tuple[tuple[str, int, int, int], ...]:
    try:
        children = sorted(path for path in root.iterdir() if path.is_dir())
    except OSError:
        return ()
    return tuple(_path_fingerprint(path) for path in children[:limit])


def _path_fingerprint(path: Path) -> tuple[str, int, int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (str(path), 0, 0, 0)
    return (str(path), int(stat.st_mtime_ns), int(stat.st_size), int(stat.st_mode))


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
    progress_events, omitted_progress_events = _status_progress_events(status_payload)
    if progress_events:
        card["progress_reporting"] = {
            "schema_version": "omh_progress_reporting/v1",
            "mode": "event_triggered",
            "timed_polling_required": False,
            "human_update_policy": "one_or_two_sentence_summary_only",
        }
        card["progress_events"] = progress_events
        card["latest_progress_event"] = progress_events[-1]
        card["omitted_progress_event_count"] = omitted_progress_events
    return card


def _status_progress_events(status_payload: dict[str, Any]) -> tuple[list[dict[str, object]], int]:
    events = status_payload.get("progress_events")
    if isinstance(events, list):
        return compact_progress_events(events)
    latest = status_payload.get("latest_progress_event")
    if isinstance(latest, dict) and latest:
        return compact_progress_events([latest])
    return [], 0


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
    if next_action in {"show_prompt_handoff", "show_runtime_handoff"}:
        label = _status_executor_label(status_payload)
        suffix = f" ({label})" if label else ""
        return kind, f"{headline}{suffix}", body, claim_boundary
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
        response = _chat_response_with_route_explanation(response, _nested(payload, "route"))
        if target_notice:
            response = _chat_response_with_target_notice(response, target_notice)
        agentic_playbook = payload.get("agentic_playbook")
        if isinstance(agentic_playbook, dict):
            response = chat_response_with_agentic_playbook(response, agentic_playbook)
        payload["chat_response"] = _chat_response_with_render_profile(
            response,
            source=str(payload.get("source", "generic")),
            source_metadata=_nested(payload, "source_metadata"),
        )
    return payload


def _chat_response_with_route_explanation(
    response: dict[str, object], route_payload: dict[str, object]
) -> dict[str, object]:
    route_explanation = _nested(route_payload, "route_explanation")
    if not route_explanation:
        return response
    updated = dict(response)
    state = dict(_nested(updated, "state"))
    workflow_explanation = dict(_nested(state, "workflow_explanation"))
    if not workflow_explanation:
        return response

    existing_reason = str(workflow_explanation.get("why_this_workflow") or "").strip()
    route_reason = str(route_explanation.get("why_this_workflow") or "").strip()
    if route_reason:
        if existing_reason and existing_reason not in route_reason:
            reason = f"{route_reason} {existing_reason}"
        else:
            reason = route_reason
        workflow_explanation["why_this_workflow"] = reason
        state["workflow_explanation_reason"] = reason
    for source_key, target_key in (
        ("action", "route_action"),
        ("next_action", "route_next_action"),
        ("recommended_reply", "route_recommended_reply"),
        ("primary_action_label", "route_primary_action_label"),
        ("primary_action_hint", "route_primary_action_hint"),
    ):
        value = route_explanation.get(source_key)
        if value:
            workflow_explanation[target_key] = value
    state["workflow_explanation"] = workflow_explanation
    updated["state"] = state
    return updated


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
    if isinstance(route.get("learning_candidate_card"), dict):
        return "route"
    if isinstance(route.get("task_card"), dict):
        return "route"
    selected = str(route.get("selected_skill", ""))
    if selected == "cancel":
        return "route"
    if selected == _ROUTER_SKILL and _is_skill_picker_invocation(message):
        return "route"
    if selected in _CLARIFICATION_SKILLS:
        return "clarify"
    if _route_is_explicit_hermes_coding_team_request(route, message):
        return "route"
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
    return is_missed_route_feedback(message)


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
    if _is_skill_picker_invocation(message) or _is_command_preview_invocation(message):
        return False
    if not _is_skill_catalog_question(message):
        return False
    return str(decision.get("selected_skill", "")) == _ROUTER_SKILL


def _route_recommendation_next_action(decision: dict[str, object]) -> str:
    recommendations = decision.get("recommendations")
    if not isinstance(recommendations, list) or not recommendations:
        return ""
    first = recommendations[0]
    if not isinstance(first, dict):
        return ""
    return str(first.get("next_action", ""))


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
    updated["route_explanation"] = route_explanation_payload(updated)
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
    updated["route_explanation"] = route_explanation_payload(updated)
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
    updated["route_explanation"] = route_explanation_payload(updated)
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
    updated["route_explanation"] = route_explanation_payload(updated)
    return updated


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


@lru_cache(maxsize=4096)
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
    default_insert_text = "/omh" if source in {"slack", "telegram"} else "./omh"
    insert_text = f"{prefix}{_COMMAND_PREVIEW_ALIAS}" if prefix else default_insert_text
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
    catalog_question = _is_skill_catalog_question(message) and not _is_skill_picker_invocation(message)
    copy_locale = detect_copy_locale(message)
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
        headline=skill_picker_headline(catalog_question=catalog_question, locale=copy_locale),
        body=_skill_picker_body(catalog_question=catalog_question, copy_locale=copy_locale),
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
                    "capability_families": picker["capability_families"],
                    "groups": picker["groups"],
                },
            ),
            _action("search_skills", "Search workflows", "secondary", payload={"input_schema": {"query": "string"}}),
            _action("show_status", "Show status", "secondary"),
        ],
        claim_boundary="Choosing a skill is routing intent only; it is not plan acceptance, dispatch, execution, review, CI, or verification evidence.",
        extra_state=extra_state,
    )


def _skill_picker_body(*, catalog_question: bool, copy_locale: str = "en") -> str:
    return localized_skill_picker_body(
        catalog_question=catalog_question,
        locale=copy_locale,
        family_lines=_skill_picker_family_body_lines(),
    )


def _skill_picker_family_body_lines() -> list[str]:
    return list(_skill_picker_family_body_lines_cached())


@lru_cache(maxsize=1)
def _skill_picker_family_body_lines_cached() -> tuple[str, ...]:
    lines = []
    for family in capability_family_cards():
        workflows = _as_string_list(family.get("primary_workflows", []))[:4]
        workflow_text = ", ".join(workflows)
        executor_choices = _as_string_list(family.get("executor_choices", []))[:3]
        if executor_choices:
            workflow_text = f"{workflow_text}; executors: {', '.join(executor_choices)}"
        lines.append(f"- {family.get('label', '')}: {workflow_text}.")
    return tuple(lines)


def _skill_picker_state(message: str, *, source: str) -> dict[str, object]:
    state = _clone_static_dict(_skill_picker_static_state_cached())
    state["trigger"] = _first_token(message)
    state["source"] = source
    return state


@lru_cache(maxsize=1)
def _skill_picker_static_state_cached() -> dict[str, object]:
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
    family_cards = _skill_picker_family_cards(options)
    return {
        "schema_version": SKILL_PICKER_SCHEMA_VERSION,
        "trigger": "",
        "source": "",
        "selection_mode": "single_select",
        "options": options,
        "featured_options": featured_options,
        "capability_families": family_cards,
        "groups": groups,
        "rendering_hints": {
            "discord": "Render Route for me first, then grouped sections; keep the full options list only as a compatibility fallback.",
            "slack": "Render Route for me first, then grouped sections or a grouped static select in the current thread.",
            "hermes_tui": "Render grouped sections with short direct invocations; keep real skill names unchanged.",
        },
        "recommended_rendering": "Show the featured Route for me option first, then capability families. Use groups/options as compatibility fallback.",
        "claim_boundary": "This picker records routing intent only; selected workflows still need their own plan, handoff, or observed evidence.",
    }


def _skill_picker_family_cards(options: list[dict[str, object]]) -> list[dict[str, object]]:
    option_ids = {str(option["id"]) for option in options}
    cards = []
    for family in capability_family_cards(option_ids):
        workflows = [
            workflow
            for workflow in _as_string_list(family.get("primary_workflows", []))
            if workflow in option_ids or workflow in {"request-to-handoff", "executor selection", "coding runtime handoff"}
        ]
        if not workflows:
            continue
        card = _compact_family_card(family)
        card["primary_workflows"] = workflows
        cards.append(card)
    return cards


def _compact_family_cards(families: list[dict[str, object]]) -> list[dict[str, object]]:
    return [_compact_family_card(family) for family in families]


def _compact_family_card(family: dict[str, object]) -> dict[str, object]:
    card = {
        "id": str(family.get("id", "")),
        "label": str(family.get("label", "")),
        "primary_workflows": _as_string_list(family.get("primary_workflows", []))[:8],
    }
    executor_choices = _as_string_list(family.get("executor_choices", []))
    if executor_choices:
        card["executor_choices"] = executor_choices
    return card


def _skill_picker_groups(options: list[dict[str, object]]) -> list[dict[str, object]]:
    by_id = {str(option["id"]): option for option in options}
    groups = []
    for group in _CONTEXT_PRIMER_GROUPS:
        group_options = [
            _compact_group_picker_option(by_id[workflow_id])
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


def _compact_group_picker_option(option: dict[str, object]) -> dict[str, object]:
    return {
        "id": str(option.get("id", "")),
        "label": str(option.get("label", "")),
        "action_id": str(option.get("action_id", "choose_skill")),
    }


def _context_primer_state() -> dict[str, object]:
    return _clone_static_dict(_context_primer_state_cached())


@lru_cache(maxsize=1)
def _context_primer_state_cached() -> dict[str, object]:
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
        "capability_families": _compact_family_cards(capability_family_cards(installed)),
        "workflow_groups": groups,
        "workflow_context_cards": workflow_context_cards(),
        "routing_rule": "Use Route for me when the user did not choose a workflow; use explicit workflow names when the user did.",
        "evidence_rule": "Prepared plans, prompts, cards, or handoffs are not execution, file generation, delivery, review, CI, merge, or verification evidence.",
        "inventory_rule": "Render the picker for common choices and use search_skills for the full installed catalog.",
    }


def _catalog_capability_summary() -> dict[str, object]:
    return _clone_static_dict(_catalog_capability_summary_cached())


@lru_cache(maxsize=1)
def _catalog_capability_summary_cached() -> dict[str, object]:
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
        "capability_families": _compact_family_cards(_as_dict_list(summary.get("capability_families", []))),
        "lanes": compact_lanes,
        "workflow_context_cards": _as_dict_list(summary.get("workflow_context_cards", [])),
        "direct_response_guidance": _as_string_list(summary.get("direct_response_guidance", [])),
        "evidence_boundary": _as_string_list(summary.get("evidence_boundary", [])),
    }


def _as_dict_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _clone_static_dict(value: dict[str, object]) -> dict[str, object]:
    cloned = _clone_static_payload(value)
    return cloned if type(cloned) is dict else {}


def _clone_static_payload(value: object) -> object:
    value_type = type(value)
    if value_type is dict:
        return {key: _clone_static_payload(item) for key, item in value.items()}
    if value_type is list:
        return [_clone_static_payload(item) for item in value]
    if value_type is tuple:
        return tuple(_clone_static_payload(item) for item in value)
    return value


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
    next_action_label = next_action.replace("_", " ")
    not_evidence_yet = _workflow_explanation_not_evidence(state, claim_boundary=claim_boundary)
    payload: dict[str, object] = {
        "schema_version": WORKFLOW_EXPLANATION_SCHEMA_VERSION,
        "selected_workflow": workflow,
        "label": label,
        "selected_harness": harness,
        "why_this_workflow": _workflow_explanation_reason(state, workflow=workflow, label=label),
        "next_action": next_action,
        "next_action_label": next_action_label,
        "recommended_reply": _workflow_recommended_reply(workflow, label, next_action_label, not_evidence_yet),
        "primary_action_label": _workflow_primary_action_label(workflow, label),
        "primary_action_hint": _workflow_primary_action_hint(workflow, label, next_action_label, not_evidence_yet),
        "not_evidence_yet": not_evidence_yet,
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


def _workflow_recommended_reply(workflow: str, label: str, next_action_label: str, not_evidence_yet: list[str]) -> str:
    name = workflow or label
    suffix = not_evidence_reply_suffix(not_evidence_yet, fallback=" This is guidance, not execution evidence.")
    return f"I will use `{name}` and start with {next_action_label}.{suffix}"


def _workflow_primary_action_label(workflow: str, label: str) -> str:
    name = workflow or label
    return f"Open {name}"


def _workflow_primary_action_hint(
    workflow: str,
    label: str,
    next_action_label: str,
    not_evidence_yet: list[str],
) -> str:
    name = workflow or label
    suffix = not_evidence_action_suffix(not_evidence_yet)
    return f"Route to `{name}` and run `{next_action_label}`{suffix}."


def _workflow_explanation_not_evidence(state: dict[str, object], *, claim_boundary: str) -> list[str]:
    explicit = state.get("evidence_not_observed")
    if isinstance(explicit, list) and explicit:
        return [str(item) for item in explicit if str(item)]
    text = claim_boundary.lower()
    if "file inspection" in text:
        items = ["file inspection"]
        if "execution" in text:
            items.append("execution")
        return items
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
    safe_body, transforms = _messenger_safe_body_cached(body)
    return safe_body, list(transforms)


@lru_cache(maxsize=4096)
def _messenger_safe_body_cached(body: str) -> tuple[str, tuple[str, ...]]:
    lines = body.splitlines()
    if not lines:
        return body, ()
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
    return "\n".join(output), tuple(sorted(set(transforms)))


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
    return [
        {"type": block_type, "text": text}
        for block_type, text in _messenger_body_blocks_cached(body)
    ]


@lru_cache(maxsize=4096)
def _messenger_body_blocks_cached(body: str) -> tuple[tuple[str, str], ...]:
    blocks: list[tuple[str, str]] = []
    current: list[str] = []
    for line in body.splitlines():
        stripped = line.strip()
        if not stripped:
            if current:
                blocks.append(("paragraph", " ".join(current)))
                current = []
            continue
        if stripped.startswith(("- ", "* ")):
            if current:
                blocks.append(("paragraph", " ".join(current)))
                current = []
            blocks.append(("bullet", stripped[2:].strip()))
            continue
        numbered_text = _numbered_list_text(stripped)
        if numbered_text:
            if current:
                blocks.append(("paragraph", " ".join(current)))
                current = []
            blocks.append(("numbered", numbered_text))
            continue
        current.append(stripped)
    if current:
        blocks.append(("paragraph", " ".join(current)))
    return tuple(blocks)


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


@lru_cache(maxsize=4096)
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
        "choose_executor": "executor_choice_required",
        "dispatch_to_executor": "handoff_prepared",
        "show_prompt_handoff": "prompt_handoff_prepared",
        "show_runtime_handoff": "runtime_handoff_prepared",
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
