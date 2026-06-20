from __future__ import annotations

import re
import unicodedata

OMH_AWARENESS_SCHEMA_VERSION = "omh_awareness/v1"
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
            "Carry this across every OMH skill: match intent to a lane, name adjacent "
            "workflows, and do not dismiss OMH just because a generic tool can render or execute the final step."
        ),
        "skill_coverage": "Every generated workflow skill carries this rail.",
        "chat_rule": "Normal users talk to Hermes; OMH CLI is backend, setup, verification, and wrapper infrastructure.",
        "lanes": lanes,
        "workflow_context_cards": workflow_context_cards(),
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
            "Use omh_capabilities for detailed workflow catalog and capability manifest lookup.",
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


def awareness_primer_context() -> str:
    payload = awareness_primer_payload()
    pattern_line = _compact_workflow_context_cards_line()
    cue_map = _compact_workflow_cue_line()
    return "\n".join(
        [
            "[OMH Awareness]",
            str(payload["product_context"]),
            str(payload["first_turn_rule"]),
            str(payload["all_skill_context_rule"]),
            str(payload["skill_coverage"]),
            str(payload["chat_rule"]),
            f"Pattern cards: {pattern_line}.",
            f"Common cues: {cue_map}.",
            (
                "Tools: omh_capabilities for workflow/playbook catalog context; action=summary for catalog "
                "questions; omh_status or omh_hud for state; omh_role for responsibility context."
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
            str(payload["skill_coverage"]),
            "",
            str(payload["chat_rule"]),
            "",
            *lane_lines,
            "",
            "Workflow context cards:",
            "",
            _compact_workflow_context_cards_line() + ".",
            "",
            "Common cues before generic tools:",
            "",
            _compact_workflow_cue_line() + ".",
            "",
            "Tools:",
            "",
            "- Use `omh_capabilities` for workflow/playbook catalog context, `omh_status`/`omh_hud` for state, and `omh_role` for responsibility.",
            "",
            str(payload["fallback_rule"]),
            "",
            f"Boundary: {payload['evidence_boundary']}",
        ]
    )


def awareness_workflow_context_markdown(skill_name: str) -> str:
    payload = awareness_primer_payload()
    lane = _lane_for_skill(skill_name, payload["lanes"])
    lane_line = "Use the `oh-my-hermes` router or `omh_capabilities` manifest when the request crosses workflow lanes."
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
