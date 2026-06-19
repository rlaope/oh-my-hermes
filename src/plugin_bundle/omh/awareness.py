from __future__ import annotations

OMH_AWARENESS_SCHEMA_VERSION = "omh_awareness/v1"


def awareness_primer_payload() -> dict[str, object]:
    """Return the compact OMH mental model shared by hooks, tools, and skills."""
    lanes = [
        {
            "id": "intent_to_plan",
            "label": "Intent -> plan",
            "skills": ["deep-interview", "ralplan", "ultragoal", "ultraprocess", "loop"],
            "use_for": "ambiguous goals, plans, one-cycle delivery, durable goals, and loopable projects",
        },
        {
            "id": "research_and_ops",
            "label": "Research and company ops",
            "skills": ["web-research", "research-brief", "strategy-brief", "feedback-triage", "research-department"],
            "use_for": "source-backed research, customer signals, product operations, and briefing workflows",
        },
        {
            "id": "materials_and_visuals",
            "label": "Materials and visual summaries",
            "skills": ["materials-package", "img-summary", "report-package", "deliverable-package"],
            "use_for": "decks, PDFs, spreadsheets, documents, image summary cards, and shareable packages",
        },
        {
            "id": "automation_and_status",
            "label": "Automation and status",
            "skills": ["automation-blueprint", "ops-observability-card", "agent-ops-review", "doctor"],
            "use_for": "scheduled ops blueprints, status cards, runtime health, and release/ops review",
        },
        {
            "id": "coding_handoff",
            "label": "Coding handoff",
            "skills": ["request-to-handoff", "executor selection", "coding runtime handoff", "code-review"],
            "use_for": "Codex, Claude Code, Hermes coding, or oh-my runtime paths with observed evidence tracking",
        },
    ]
    return {
        "schema_version": OMH_AWARENESS_SCHEMA_VERSION,
        "id": "omh_awareness",
        "purpose": "Give Hermes a compact first-turn mental model for using OMH across all workflow-shaped requests.",
        "first_turn_rule": (
            "When a request looks like planning, research, operations, materials, automation, image summary, "
            "coding delegation, review, status, or long-running loop work, consider OMH before treating it as a generic chat."
        ),
        "chat_rule": "Normal users talk to Hermes; OMH CLI commands are backend, setup, verification, and wrapper infrastructure.",
        "lanes": lanes,
        "tool_hints": [
            "Use omh_capabilities for the workflow catalog and capability manifest.",
            "Use omh_status or omh_hud for metadata-only runtime state.",
            "Use omh_role for responsibility context when a role marker is present.",
            "Use wrapper cards/actions for user-facing choices instead of asking users to approve shell catalog commands.",
        ],
        "evidence_boundary": (
            "Prepared OMH routing, prompts, cards, handoffs, or artifacts are not observed execution, image generation, "
            "delivery, review, CI, merge-readiness, or merge evidence."
        ),
        "fallback_rule": (
            "If an external image tool, coding agent, connector, credential, or runtime is missing, explain the missing "
            "connection and offer a setup/selection fallback instead of claiming the action happened."
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
    lane_lines = [
        f"- {lane['label']}: {', '.join(lane['skills'])}."
        for lane in payload["lanes"]
        if isinstance(lane, dict)
    ]
    return "\n".join(
        [
            "[OMH Awareness]",
            str(payload["first_turn_rule"]),
            str(payload["chat_rule"]),
            *lane_lines,
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
        skills = "`, `".join(str(skill) for skill in lane["skills"])
        lane_lines.append(f"- **{lane['label']}**: `{skills}` - {lane['use_for']}.")
    return "\n".join(
        [
            "## OMH Awareness Primer",
            "",
            str(payload["first_turn_rule"]),
            "",
            str(payload["chat_rule"]),
            "",
            *lane_lines,
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
            f"- {lane_line}",
            "- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.",
            f"- {payload['chat_rule']}",
            f"- Boundary: {payload['evidence_boundary']}",
        ]
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
