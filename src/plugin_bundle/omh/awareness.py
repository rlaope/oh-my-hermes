from __future__ import annotations

import hashlib
import re
import unicodedata

OMH_AWARENESS_SCHEMA_VERSION = "omh_awareness/v1"
OMH_ROUTE_HINT_SCHEMA_VERSION = "omh_route_hint/v1"
OMH_GENERIC_TOOL_CHECKPOINT_SCHEMA_VERSION = "omh_generic_tool_checkpoint/v1"
GENERIC_TOOL_CHECKPOINT_TEXT = "Before generic tools, check OMH prep/status/learning; if relevant, name the workflow first."
GENERIC_TOOL_CHECKPOINT_APPLIES_BEFORE = ("image tools", "file tools", "search tools", "coding tools")
GENERIC_TOOL_CHECKPOINT_ROUTES = (
    {
        "tool_family": "image_tools",
        "applies_before": ("image generation", "local rendering", "visual design tools"),
        "primary_workflow": "img-summary",
        "preferred_workflows": ("img-summary", "materials-package", "report-package"),
        "primary_next_action": "prepare_visual_prompt_card",
        "fallback_action": "choose_image_generator_or_setup",
        "not_evidence_yet": ("image generation", "visual QA", "attachment", "delivery"),
    },
    {
        "tool_family": "file_tools",
        "applies_before": ("PPT/PDF/XLSX/DOC/HWP generation", "file conversion", "attachment packaging"),
        "primary_workflow": "materials-package",
        "preferred_workflows": ("materials-package", "deliverable-package", "report-package"),
        "primary_next_action": "prepare_material_package",
        "fallback_action": "confirm_target_format_and_generator",
        "not_evidence_yet": ("file export", "render QA", "attachment", "delivery"),
    },
    {
        "tool_family": "search_tools",
        "applies_before": ("web search", "source lookup", "market/news/paper research"),
        "primary_workflow": "web-research",
        "preferred_workflows": ("web-research", "research-department", "research-brief"),
        "primary_next_action": "gather_source_backed_evidence",
        "fallback_action": "ask_for_scope_or_source_constraints",
        "not_evidence_yet": ("source retrieval", "source verification", "synthesis approval", "delivery"),
    },
    {
        "tool_family": "coding_tools",
        "applies_before": ("Codex", "Claude Code", "Hermes coding", "oh-my runtime handoff"),
        "primary_workflow": "ultraprocess",
        "preferred_workflows": ("ultraprocess", "ralplan", "code-review", "agent-ops-review"),
        "primary_next_action": "prepare_one_cycle_delivery",
        "fallback_action": "choose_coding_agent_or_runtime",
        "not_evidence_yet": ("executor dispatch", "implementation", "review", "CI", "merge"),
    },
)
ROUTER_KEYWORD_SKILLS = (
    "deep-interview",
    "ralplan",
    "ultragoal",
    "loop",
    "ultraprocess",
    "web-research",
    "research-department",
    "feedback-triage",
    "materials-package",
    "img-summary",
    "automation-blueprint",
    "workflow-learning",
    "code-review",
    "team",
    "ultrawork",
    "ultraqa",
    "doctor",
)

LANE_CROSS_LANE_EXAMPLES = {
    "intent_to_plan": [
        "ambitious goal -> loopability check -> loop or ultraprocess -> verification status",
        "fuzzy feature request -> deep-interview -> ralplan -> accepted plan",
    ],
    "research_and_ops": [
        "customer signal -> feedback-triage -> investigation plan -> coding handoff -> status",
        "market topic -> web-research -> research-brief -> strategy-brief -> operating-rhythm",
    ],
    "materials_and_visuals": [
        "meeting notes -> meeting-brief -> report-package -> img-summary -> delivery evidence",
        "source spreadsheet -> materials-package -> report-package -> observed export evidence",
    ],
    "automation_and_status": [
        "daily digest request -> automation-blueprint -> confirmation card -> observed schedule evidence",
        "workflow attempt -> workflow-learning -> eval -> improvement candidate or regression case",
        "runtime confusion -> doctor or agent-ops-review -> status card -> next repair action",
    ],
    "coding_handoff": [
        "accepted plan -> ultraprocess -> coding handoff -> review and CI evidence",
        "risky change -> ralplan -> executor selection -> observed coding-agent status",
    ],
}
WORKFLOW_CONTEXT_CARDS = (
    {
        "id": "intent_to_plan",
        "label": "Intent to plan",
        "user_signal": "fuzzy goal, ambitious target, safe feature, or one-cycle delivery request",
        "omh_pattern": "clarify or plan first, then move to ultragoal, ultraprocess, loop, or handoff only when concrete",
        "representative_workflows": ("deep-interview", "ralplan", "ultragoal", "loop", "ultraprocess"),
        "user_examples": ("Make onboarding feel smoother", "Make this repo star-worthy"),
        "first_response_shape": "Name the ambiguity, choose clarify/plan/loop/process, then state the next concrete action and what is not evidence yet.",
        "not_evidence_until_observed": ("plan acceptance", "executor dispatch", "verification"),
    },
    {
        "id": "research_and_ops",
        "label": "Research and ops",
        "user_signal": "customer signal, meeting notes, market question, strategy request, or operating record",
        "omh_pattern": "collect evidence, separate source notes from synthesis, then create a brief, decision, or status artifact",
        "representative_workflows": ("web-research", "research-department", "feedback-triage", "meeting-brief", "strategy-brief"),
        "user_examples": ("Payment failures keep coming up", "Track competitor news every morning"),
        "first_response_shape": "Name the source/synthesis split, pick the research or ops workflow, then ask for missing source evidence or cadence only when needed.",
        "not_evidence_until_observed": ("source retrieval", "decision approval", "delivery"),
    },
    {
        "id": "materials_and_visuals",
        "label": "Materials and visuals",
        "user_signal": "deck, PDF, spreadsheet, document, HWP, report, image card, or shareable summary",
        "omh_pattern": "shape the deliverable contract, prepare prompts or package metadata, then record generation and QA only when observed",
        "representative_workflows": ("materials-package", "report-package", "deliverable-package", "img-summary"),
        "user_examples": ("Turn this PR into a reviewer image card", "Make this spreadsheet a PDF report package"),
        "first_response_shape": "Separate copy/layout/package prep from generated file or image evidence, then offer revise/copy/generate/record actions.",
        "not_evidence_until_observed": ("file export", "image generation", "visual QA", "attachment"),
    },
    {
        "id": "automation_and_status",
        "label": "Automation and status",
        "user_signal": "recurring digest, cron-like request, gateway command, health check, status confusion, workflow learning, or runtime question",
        "omh_pattern": "prepare a schedule/status/repair/learning card, name required tools or evidence, then keep observed runtime state separate",
        "representative_workflows": (
            "automation-blueprint",
            "agent-ops-review",
            "workflow-learning",
            "toolbelt-readiness",
            "doctor",
        ),
        "user_examples": (
            "Every morning send a digest if something changed",
            "Why did this route to plan? Make it a regression.",
        ),
        "first_response_shape": "Show the prepared status, schedule, or learning shape, name the missing evidence, and expose refresh, repair, or review actions.",
        "not_evidence_until_observed": ("schedule creation", "connector I/O", "runtime load", "skill patch approval"),
    },
    {
        "id": "coding_handoff",
        "label": "Coding handoff",
        "user_signal": "risky code change, issue-to-PR, review, CI, merge, coding-agent progress, or Hermes coding request",
        "omh_pattern": "choose the coding owner, prepare executor-neutral handoff or Hermes coding team path, then track dispatch and result evidence",
        "representative_workflows": ("ultraprocess", "code-review", "team", "ultrawork", "ultraqa"),
        "user_examples": ("Turn this issue into a PR-ready plan", "Is the Codex run done yet?"),
        "first_response_shape": "State the selected coding owner or choice point, prepare the handoff/status, and keep dispatch, result, review, CI, and merge evidence separate.",
        "not_evidence_until_observed": ("dispatch", "implementation", "review", "CI", "merge"),
    },
)
_WORKFLOW_CONTEXT_CARD_BY_WORKFLOW = {
    "deep-interview": "intent_to_plan",
    "plan": "intent_to_plan",
    "ralplan": "intent_to_plan",
    "ralph": "intent_to_plan",
    "ultragoal": "intent_to_plan",
    "loop": "intent_to_plan",
    "ultraprocess": "intent_to_plan",
    "performance-goal": "intent_to_plan",
    "web-research": "research_and_ops",
    "research-department": "research_and_ops",
    "research-brief": "research_and_ops",
    "best-practice-research": "research_and_ops",
    "autoresearch-goal": "research_and_ops",
    "feedback-triage": "research_and_ops",
    "meeting-brief": "research_and_ops",
    "strategy-brief": "research_and_ops",
    "operating-rhythm": "research_and_ops",
    "materials-package": "materials_and_visuals",
    "report-package": "materials_and_visuals",
    "deliverable-package": "materials_and_visuals",
    "img-summary": "materials_and_visuals",
    "automation-blueprint": "automation_and_status",
    "agent-board": "automation_and_status",
    "agent-ops-review": "automation_and_status",
    "doctor": "automation_and_status",
    "gateway-intent-card": "automation_and_status",
    "memory-curation-review": "automation_and_status",
    "ops-observability-card": "automation_and_status",
    "ops-review": "automation_and_status",
    "reliability-review": "automation_and_status",
    "skill": "automation_and_status",
    "toolbelt-readiness": "automation_and_status",
    "voice-operator": "automation_and_status",
    "wiki": "automation_and_status",
    "workflow-learning": "automation_and_status",
    "ai-slop-cleaner": "coding_handoff",
    "ask": "coding_handoff",
    "code-review": "coding_handoff",
    "cto-loop": "coding_handoff",
    "deploy-and-monitor": "coding_handoff",
    "executor-runtime-readiness": "coding_handoff",
    "github-event-ops": "coding_handoff",
    "idea-to-deploy": "coding_handoff",
    "team": "coding_handoff",
    "ultraqa": "coding_handoff",
    "ultrawork": "coding_handoff",
}
_AWARENESS_MESSAGE_MARKERS = (
    "oh-my-hermes",
    "pull request",
    "image card",
    "summary card",
    "infographic",
    "poster",
    "shareable card",
    "visual one-pager",
    "계획",
    "리서치",
    "회의",
    "회의록",
    "피드백",
    "이슈",
    "버그",
    "상태",
    "자동화",
    "루프",
    "코딩",
    "리뷰",
    "릴리즈",
    "보고서",
    "자료",
    "이미지",
    "포스터",
    "공유용 카드",
    "요약 카드",
    "画像",
    "海报",
    "海報",
)
_AWARENESS_TOKEN_MARKERS = frozenset(
    {
        "omh",
        "workflow",
        "workflows",
        "skill",
        "skills",
        "plan",
        "planning",
        "research",
        "brief",
        "meeting",
        "feedback",
        "issue",
        "bug",
        "pr",
        "status",
        "automation",
        "cron",
        "schedule",
        "loop",
        "handoff",
        "coding",
        "codex",
        "claude",
        "review",
        "release",
        "deck",
        "ppt",
        "pdf",
        "spreadsheet",
        "image",
        "infographic",
        "poster",
        "one-pager",
        "visual",
        "deliverable",
        "material",
    }
)
_ROUTE_HINT_RULES = (
    {
        "id": "missed_workflow",
        "workflow": "workflow-learning",
        "lane": "automation_and_status",
        "next_action": "record_missed_route",
        "reason": "The user is reporting that OMH or the expected workflow was not used.",
        "phrases": (
            "missed route",
            "missed workflow",
            "did not use omh",
            "omh was not used",
            "omx was not used",
            "not use omh",
            "omh 안 썼어",
            "omh 안 썼",
            "워크플로 누락",
            "라우팅 누락",
        ),
        "tokens": ("missed",),
        "adjacent_workflows": ("doctor", "agent-ops-review"),
    },
    {
        "id": "visual_summary",
        "workflow": "img-summary",
        "lane": "materials_and_visuals",
        "next_action": "prepare_visual_prompt_card",
        "reason": "The user is asking for an image card, infographic, poster, or shareable visual summary.",
        "phrases": (
            "image card",
            "summary card",
            "infographic",
            "poster",
            "visual one-pager",
            "shareable visual",
            "generate image",
            "image summary",
            "이미지",
            "포스터",
            "요약 카드",
            "공유용 카드",
            "画像",
            "海报",
            "海報",
        ),
        "tokens": ("image", "infographic", "poster", "visual"),
        "adjacent_workflows": ("materials-package", "report-package"),
    },
    {
        "id": "customer_signal",
        "workflow": "feedback-triage",
        "lane": "research_and_ops",
        "next_action": "classify_signal_and_prepare_investigation",
        "reason": "The user is describing customer feedback, bugs, issues, or product signals that need triage before implementation.",
        "phrases": (
            "customer feedback",
            "payment failure",
            "payment failures",
            "bug report",
            "issue triage",
            "user feedback",
            "결제 실패",
            "고객 피드백",
            "버그",
            "이슈",
            "피드백",
        ),
        "tokens": ("feedback", "bug", "issue", "triage"),
        "adjacent_workflows": ("web-research", "github-event-ops", "coding handoff"),
    },
    {
        "id": "scheduled_ops",
        "workflow": "automation-blueprint",
        "lane": "automation_and_status",
        "next_action": "prepare_scheduled_ops_blueprint",
        "reason": "The user is asking for recurring, scheduled, cron-like, or digest-style work.",
        "phrases": (
            "every morning",
            "every day",
            "daily digest",
            "weekly digest",
            "cron",
            "scheduled",
            "recurring",
            "매일",
            "매주",
            "자동화",
            "스케줄",
        ),
        "tokens": ("cron", "schedule", "scheduled", "recurring", "digest"),
        "adjacent_workflows": ("research-department", "ops-observability-card"),
    },
    {
        "id": "source_research",
        "workflow": "web-research",
        "lane": "research_and_ops",
        "next_action": "gather_source_backed_evidence",
        "reason": "The user is asking for current, source-backed, market, competitor, paper, or news research.",
        "phrases": (
            "web search",
            "best practice",
            "competitor",
            "market research",
            "latest news",
            "source-backed",
            "paper",
            "논문",
            "리서치",
            "검색",
            "시장 조사",
            "경쟁사",
        ),
        "tokens": ("research", "sources", "competitor", "market", "paper", "news"),
        "adjacent_workflows": ("research-brief", "research-department", "strategy-brief"),
    },
    {
        "id": "coding_delivery",
        "workflow": "ultraprocess",
        "lane": "coding_handoff",
        "next_action": "prepare_one_cycle_delivery",
        "reason": "The user is asking for coding delivery, PR preparation, implementation, review, CI, or merge-oriented work.",
        "phrases": (
            "pull request",
            "code review",
            "ci failed",
            "merge this",
            "implement",
            "coding agent",
            "codex",
            "claude code",
            "pr 올려",
            "머지",
            "코딩",
            "구현",
            "리뷰",
        ),
        "tokens": ("pr", "implementation", "implement", "review", "ci", "merge", "codex", "claude"),
        "adjacent_workflows": ("ralplan", "code-review", "agent-ops-review"),
    },
)


def router_keyword_summary() -> str:
    """Return representative workflow keywords for router/snippet guidance."""
    return ", ".join(f"`{skill}`" for skill in ROUTER_KEYWORD_SKILLS)


def awareness_lane_examples(lane_id: str) -> list[str]:
    """Return compact examples relevant to one OMH awareness lane."""
    return list(LANE_CROSS_LANE_EXAMPLES.get(lane_id, []))


def workflow_context_cards() -> list[dict[str, object]]:
    """Return compact workflow cards that teach Hermes when OMH should help."""
    return [
        {
            "id": card["id"],
            "label": card["label"],
            "user_signal": card["user_signal"],
            "omh_pattern": card["omh_pattern"],
            "representative_workflows": list(card["representative_workflows"]),
            "user_examples": list(card["user_examples"]),
            "first_response_shape": card["first_response_shape"],
            "not_evidence_until_observed": list(card["not_evidence_until_observed"]),
        }
        for card in WORKFLOW_CONTEXT_CARDS
    ]


def workflow_context_card_for_workflow(workflow: str) -> dict[str, object]:
    """Return the OMH pattern card that should frame one selected workflow."""
    workflow_key = workflow.strip().casefold()
    card_id = _WORKFLOW_CONTEXT_CARD_BY_WORKFLOW.get(workflow_key, "")
    if not card_id:
        for card in WORKFLOW_CONTEXT_CARDS:
            representative_workflows = {str(item).casefold() for item in card["representative_workflows"]}
            if workflow_key in representative_workflows:
                card_id = str(card["id"])
                break
    if not card_id:
        return {}
    for card in workflow_context_cards():
        if card["id"] == card_id:
            return card
    return {}


def awareness_context_matches_message(message: str) -> bool:
    """Return true when a non-first-turn message should refresh OMH context."""
    text = unicodedata.normalize("NFKC", message).casefold()
    if not text.strip():
        return False
    tokens = set(re.findall(r"[a-z0-9][a-z0-9_-]*", text))
    return bool(tokens & _AWARENESS_TOKEN_MARKERS) or any(
        marker in text for marker in _AWARENESS_MESSAGE_MARKERS
    )


def awareness_route_hint(message: str, *, max_hints: int = 2) -> dict[str, object]:
    """Return bounded message-specific workflow hints without exposing raw text."""
    normalized = unicodedata.normalize("NFKC", message).casefold()
    tokens = set(re.findall(r"[a-z0-9][a-z0-9_-]*", normalized))
    hint_limit = max(max_hints, 0)
    hints: list[dict[str, object]] = []
    if normalized.strip() and hint_limit:
        for rule in _ROUTE_HINT_RULES:
            phrase_matches = [phrase for phrase in rule["phrases"] if phrase in normalized]
            token_matches = [token for token in rule["tokens"] if token in tokens]
            if not phrase_matches and not token_matches:
                continue
            workflow = str(rule["workflow"])
            context_card = workflow_context_card_for_workflow(workflow)
            hints.append(
                {
                    "id": str(rule["id"]),
                    "workflow": workflow,
                    "lane": str(rule["lane"]),
                    "next_action": str(rule["next_action"]),
                    "reason": str(rule["reason"]),
                    "matched_cues": _bounded_matches(phrase_matches + token_matches),
                    "adjacent_workflows": list(rule["adjacent_workflows"]),
                    "workflow_context_card": context_card,
                    "not_evidence_yet": list(context_card.get("not_evidence_until_observed", []))
                    if isinstance(context_card, dict)
                    else [],
                }
            )
            if len(hints) >= hint_limit:
                break
    return {
        "schema_version": OMH_ROUTE_HINT_SCHEMA_VERSION,
        "status": "hinted" if hints else "no_hint",
        "message_sha256": hashlib.sha256(message.encode("utf-8")).hexdigest() if message else "",
        "message_length": len(message),
        "primary_workflow": str(hints[0]["workflow"]) if hints else "",
        "primary_next_action": str(hints[0]["next_action"]) if hints else "",
        "hints": hints,
        "privacy": {
            "mode": "metadata_only",
            "raw_prompt_stored": False,
            "stored_fields": ["message hash", "message length", "matched cue labels", "workflow hint"],
        },
        "claim_boundary": (
            "OMH route hints are local deterministic prompt context only. They are not workflow execution, "
            "tool invocation, generated output, verification, review, CI, merge, or proof that routing was correct."
        ),
    }


def awareness_route_hint_context(message: str, *, max_hints: int = 2) -> str:
    """Return compact hook text for message-specific workflow hints."""
    payload = awareness_route_hint(message, max_hints=max_hints)
    if payload.get("status") != "hinted":
        return ""
    lines = [
        "[OMH Route Hint]",
        "Use this message-specific OMH hint before generic chat/tools when it fits the user intent.",
    ]
    for hint in payload["hints"]:
        if not isinstance(hint, dict):
            continue
        adjacent = ", ".join(str(item) for item in hint.get("adjacent_workflows", []))
        lines.append(
            f"- workflow={hint.get('workflow')}; lane={hint.get('lane')}; "
            f"next_action={hint.get('next_action')}; reason={hint.get('reason')}"
        )
        if adjacent:
            lines.append(f"  adjacent_workflows={adjacent}.")
        not_evidence = ", ".join(str(item) for item in hint.get("not_evidence_yet", [])[:4])
        if not_evidence:
            lines.append(f"  not_evidence_yet={not_evidence}.")
    lines.append("Boundary: " + str(payload["claim_boundary"]))
    return "\n".join(lines)


def awareness_primer_payload() -> dict[str, object]:
    """Return the compact OMH mental model shared by hooks, tools, and skills."""
    lanes = [
        {
            "id": "intent_to_plan",
            "label": "Intent -> plan",
            "skills": [
                "oh-my-hermes",
                "deep-interview",
                "plan",
                "ralplan",
                "ultragoal",
                "ultraprocess",
                "loop",
                "ralph",
                "performance-goal",
            ],
            "use_for": "ambiguous goals, plans, one-cycle delivery, durable goals, and loopable projects",
        },
        {
            "id": "research_and_ops",
            "label": "Research and company ops",
            "skills": [
                "web-research",
                "best-practice-research",
                "autoresearch-goal",
                "research-brief",
                "strategy-brief",
                "feedback-triage",
                "research-department",
                "meeting-brief",
                "operating-rhythm",
                "ops-review",
                "reliability-review",
            ],
            "use_for": "source-backed research, customer signals, product operations, and briefing workflows",
        },
        {
            "id": "materials_and_visuals",
            "label": "Materials and visual summaries",
            "skills": ["materials-package", "img-summary", "report-package", "deliverable-package", "wiki"],
            "use_for": "decks, PDFs, spreadsheets, documents, image summary cards, and shareable packages",
        },
        {
            "id": "automation_and_status",
            "label": "Automation and status",
            "skills": [
                "automation-blueprint",
                "github-event-ops",
                "agent-board",
                "gateway-intent-card",
                "voice-operator",
                "toolbelt-readiness",
                "ops-observability-card",
                "agent-ops-review",
                "memory-curation-review",
                "workflow-learning",
                "doctor",
                "skill",
                "ask",
                "cancel",
            ],
            "use_for": "scheduled ops, gateway cards, boards, tool readiness, status, health, and release/ops review",
        },
        {
            "id": "coding_handoff",
            "label": "Coding handoff",
            "skills": [
                "idea-to-deploy",
                "cto-loop",
                "deploy-and-monitor",
                "code-review",
                "ultrawork",
                "team",
                "ultraqa",
                "ai-slop-cleaner",
                "executor-runtime-readiness",
                "request-to-handoff",
                "executor selection",
                "coding runtime handoff",
            ],
            "use_for": "Codex, Claude Code, Hermes coding, or oh-my runtime paths with observed evidence tracking",
        },
    ]
    return {
        "schema_version": OMH_AWARENESS_SCHEMA_VERSION,
        "id": "omh_awareness",
        "purpose": "Give Hermes a compact first-turn mental model for using OMH across all workflow-shaped requests.",
        "product_context": (
            "OMH is a Hermes-native workflow pack: it helps Hermes choose skills, shape work, prepare artifacts, "
            "show status, and hand off without hiding unobserved execution."
        ),
        "first_turn_rule": (
            "When a request asks for planning, research, ops records, files/materials, visual summaries, image cards, "
            "automation, coding delegation, review, status, or long-running loops, consider OMH before generic chat "
            "or generic tools."
        ),
        "all_skill_context_rule": (
            "Across every OMH skill: match intent to a lane, name adjacent workflows, "
            "and do not dismiss OMH because a generic tool can render or execute."
        ),
        "generic_tool_checkpoint": GENERIC_TOOL_CHECKPOINT_TEXT,
        "skill_coverage": "Every generated workflow skill carries this rail.",
        "chat_rule": "Normal users talk to Hermes; OMH CLI is backend, setup, verification, and wrapper infrastructure.",
        "lanes": lanes,
        "workflow_context_cards": workflow_context_cards(),
        "generic_tool_checkpoint_routes": generic_tool_checkpoint_routes(),
        "cross_lane_examples": [
            example
            for lane_examples in LANE_CROSS_LANE_EXAMPLES.values()
            for example in lane_examples[:1]
        ],
        "workflow_cues": [
            {
                "cue": "meeting notes, retros, decisions, or follow-ups",
                "route": "operating-rhythm or meeting-brief before generic summarization",
            },
            {
                "cue": "PR, issue, bug, customer feedback, or release summaries",
                "route": "github-event-ops, feedback-triage, report-package, or img-summary by output shape",
            },
            {
                "cue": "current sources, market/news research, or evidence-backed answers",
                "route": "web-research, research-brief, or research-department before unsupported recall",
            },
            {
                "cue": "decks, PDFs, spreadsheets, docs, HWP, or upload-ready files",
                "route": "materials-package or report-package before ad hoc file narration",
            },
            {
                "cue": "image cards, infographics, briefing posters, or shareable visuals",
                "route": "img-summary before generic image generation or local rendering",
            },
            {
                "cue": "coding, risky changes, executor status, review, CI, or merge state",
                "route": "ultraprocess, coding handoff, code-review, or agent-ops-review with observed evidence boundaries",
            },
            {
                "cue": "workflow trace, skill improvement, regression corpus, or why-routing questions",
                "route": "workflow-learning before ad hoc self-critique or automatic skill patching",
            },
        ],
        "context_surfaces": [
            "installed skills and workflow picker",
            "capability manifest",
            "runtime status and HUD",
            "roles and operating model",
            "wrapper cards and actions",
            "local artifacts and evidence records",
        ],
        "tool_hints": [
            "Use omh_capabilities action=summary when the user asks what OMH can do or which workflows are available.",
            "Use omh_recommend when the user gives a natural-language request and Hermes needs the nearest OMH workflow without shell approval.",
            "Use omh_capabilities for detailed workflow catalog and capability manifest lookup.",
            "Use omh_probe when the user asks whether OMH is installed, what is missing, or what the next setup/runtime evidence step should be.",
            "Use omh_status or omh_hud for metadata-only runtime state.",
            "Use omh_role for responsibility context when a role marker is present.",
            "Use wrapper cards/actions for user-facing choices instead of asking users to approve shell catalog commands.",
        ],
        "evidence_boundary": (
            "Prepared OMH routing, prompts, cards, handoffs, or artifacts are not observed execution, image generation, "
            "delivery, review, CI, merge-readiness, or merge evidence."
        ),
        "fallback_rule": (
            "If an external image tool, coding agent, connector, credential, or runtime is missing, offer setup/selection "
            "fallback instead of claiming the action happened."
        ),
        "non_goals": [
            "no hidden executor dispatch",
            "no hidden image generation",
            "no hidden platform transport",
            "no Hermes core patching",
        ],
        "source_refs": [
            "src/plugin_bundle/omh/awareness.py",
            "src/skills/render.py",
            "src/capabilities/registry.py",
        ],
    }


def awareness_generic_tool_checkpoint_payload() -> dict[str, object]:
    return {
        "schema_version": OMH_GENERIC_TOOL_CHECKPOINT_SCHEMA_VERSION,
        "label": "OMH-first checkpoint",
        "body": GENERIC_TOOL_CHECKPOINT_TEXT,
        "applies_before": list(GENERIC_TOOL_CHECKPOINT_APPLIES_BEFORE),
        "routes": generic_tool_checkpoint_routes(),
        "operating_rule": (
            "If a route matches, show the preferred OMH workflow/action first. "
            "Use the generic tool only after the user accepts the route or when the route does not fit."
        ),
        "claim_boundary": "Advisory routing context only; not workflow execution or generic tool invocation evidence.",
    }


def generic_tool_checkpoint_routes() -> list[dict[str, object]]:
    """Return compact OMH-first route hints for common generic tool families."""
    return [
        {
            "tool_family": str(route["tool_family"]),
            "applies_before": list(route["applies_before"]),
            "primary_workflow": str(route["primary_workflow"]),
            "preferred_workflows": list(route["preferred_workflows"]),
            "primary_next_action": str(route["primary_next_action"]),
            "fallback_action": str(route["fallback_action"]),
            "not_evidence_yet": list(route["not_evidence_yet"]),
        }
        for route in GENERIC_TOOL_CHECKPOINT_ROUTES
    ]


def awareness_primer_context() -> str:
    payload = awareness_primer_payload()
    pattern_line = _compact_workflow_context_cards_line()
    cue_map = _compact_workflow_cue_line()
    tool_map = _compact_generic_tool_checkpoint_line()
    return "\n".join(
        [
            "[OMH Awareness]",
            str(payload["product_context"]),
            str(payload["first_turn_rule"]),
            str(payload["all_skill_context_rule"]),
            str(payload["generic_tool_checkpoint"]),
            str(payload["skill_coverage"]),
            str(payload["chat_rule"]),
            f"Pattern cards: {pattern_line}.",
            f"Common cues: {cue_map}.",
            (
                f"Tools: {tool_map}; omh_interact records chat/session metadata; "
                "omh_recommend routes; omh_capabilities catalogs; omh_probe roadmaps; "
                "omh_status/hud state; omh_role role context."
            ),
            str(payload["fallback_rule"]),
            "Boundary: " + str(payload["evidence_boundary"]),
        ]
    )


def awareness_primer_markdown() -> str:
    payload = awareness_primer_payload()
    lane_lines = []
    for lane in payload["lanes"]:
        if not isinstance(lane, dict):
            continue
        skills = [str(skill) for skill in lane["skills"][:4]]
        lane_lines.append(
            f"- **{lane['label']}**: {lane['use_for']}. Key: `{'`, `'.join(skills)}`."
        )
    return "\n".join(
        [
            "## OMH Awareness Primer",
            "",
            str(payload["product_context"]),
            "",
            str(payload["first_turn_rule"]),
            "",
            str(payload["all_skill_context_rule"]),
            "",
            str(payload["generic_tool_checkpoint"]),
            "",
            str(payload["skill_coverage"]),
            "",
            str(payload["chat_rule"]),
            *lane_lines,
            "",
            "Workflow context cards:",
            _compact_workflow_context_cards_line() + ".",
            "",
            "Common cues before generic tools:",
            _compact_workflow_cue_line() + ".",
            "",
            "Generic tool map:",
            _compact_generic_tool_checkpoint_line() + ".",
            "",
            "Tools:",
            "- Tools: `omh_interact` chat/session meta; `omh_recommend`; `omh_capabilities`; `omh_probe`; `omh_status`/`omh_hud`; `omh_role`.",
            "",
            str(payload["fallback_rule"]),
            "",
            f"Boundary: {payload['evidence_boundary']}",
        ]
    )


def awareness_workflow_context_markdown(skill_name: str) -> str:
    payload = awareness_primer_payload()
    lane = _lane_for_skill(skill_name, payload["lanes"])
    lane_line = "Use `omh_recommend` or the `oh-my-hermes` router for workflow choice, and `omh_capabilities` for manifest detail."
    if lane:
        skills = "`, `".join(str(skill) for skill in lane["skills"])
        lane_line = f"Current lane: **{lane['label']}** (`{skills}`) - {lane['use_for']}."
    return "\n".join(
        [
            "## OMH Context Rail",
            "",
            f"- This skill is part of OMH's Hermes workflow layer, not a standalone executor.",
            f"- Product context: {payload['product_context']}",
            f"- {lane_line}",
            "- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.",
            f"- Cross-skill context: {payload['all_skill_context_rule']}",
            f"- Generic-tool checkpoint: {_compact_generic_tool_checkpoint_line()}.",
            f"- Coverage: {payload['skill_coverage']}",
            f"- {payload['chat_rule']}",
            f"- Boundary: {payload['evidence_boundary']}",
        ]
    )


def _compact_workflow_cue_line() -> str:
    return (
        "notes/retros -> operating-rhythm/meeting-brief; PR/issue/bug/feedback/release -> github-event-ops, "
        "feedback-triage, report-package, or img-summary; sources/news -> web-research or research-department; "
        "decks/PDF/sheets/docs/HWP -> materials-package or report-package; image cards/infographics -> img-summary; "
        "coding/status/review/CI/merge -> ultraprocess, code-review, or agent-ops-review; "
        "trace/improve/regression -> workflow-learning"
    )


def _compact_workflow_context_cards_line() -> str:
    return (
        "intent -> deep-interview/ralplan/loop/ultraprocess; "
        "signals -> web-research/research-department/feedback-triage/meeting-brief; "
        "materials -> materials-package/report-package/img-summary; "
        "automation/status/learning -> automation-blueprint/agent-ops-review/workflow-learning/doctor; "
        "code -> ultraprocess/code-review/team/ultrawork/ultraqa"
    )


def _compact_generic_tool_checkpoint_line() -> str:
    return (
        "image->img-summary; file->materials-package; "
        "search->web-research; code->ultraprocess/ralplan/review"
    )


def _bounded_matches(matches: list[str]) -> list[str]:
    seen: list[str] = []
    for item in matches:
        value = item.strip()
        if value and value not in seen:
            seen.append(value)
        if len(seen) >= 4:
            break
    return seen


def _lane_for_skill(skill_name: str, lanes: object) -> dict[str, object] | None:
    if not isinstance(lanes, list):
        return None
    normalized = skill_name.strip()
    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        skills = lane.get("skills", [])
        if isinstance(skills, list) and normalized in {str(skill) for skill in skills}:
            return lane
    return None
