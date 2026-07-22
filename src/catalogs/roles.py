from __future__ import annotations

from dataclasses import dataclass


ROLE_CONTRACT_VERSION = "omh_role_surface/v1"
ROLE_WORKFLOW_CONTEXT_RULE = (
    "Use this role as OMH workflow-layer responsibility context: route the user's request to the nearest skill, "
    "name adjacent OMH workflows when the work crosses lanes, and keep status/evidence boundaries visible."
)
ROLE_CHAT_RULE = (
    "Normal users talk to Hermes; role names help Hermes explain ownership and next action without making the user "
    "learn backend OMH commands."
)
ROLE_BOUNDARY_RULE = (
    "Role selection is prepared guidance only. It is not worker dispatch, tool execution, file generation, delivery, "
    "review, CI, merge-readiness, or merge evidence."
)


@dataclass(frozen=True)
class RoleDefinition:
    id: str
    title: str
    purpose: str
    owns: tuple[str, ...]
    primary_skills: tuple[str, ...]
    primary_harnesses: tuple[str, ...]
    wrapper_actions: tuple[str, ...]
    evidence_boundary: str
    legacy_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "display_name": self.title,
            "legacy_ids": list(self.legacy_ids),
            "purpose": self.purpose,
            "owns": list(self.owns),
            "primary_skills": list(self.primary_skills),
            "primary_harnesses": list(self.primary_harnesses),
            "wrapper_actions": list(self.wrapper_actions),
            "workflow_context_rule": ROLE_WORKFLOW_CONTEXT_RULE,
            "chat_rule": ROLE_CHAT_RULE,
            "role_boundary_rule": ROLE_BOUNDARY_RULE,
            "evidence_boundary": self.evidence_boundary,
            "runtime_claim": "descriptor_not_runtime_agent",
        }


_ROLES = (
    RoleDefinition(
        id="guide",
        title="Guide",
        purpose="Own first-touch routing, workflow selection, concise clarification, and the next visible Hermes action.",
        owns=(
            "Plain request intake and route explanation",
            "Skill or playbook recommendation",
            "One focused clarification when routing signals conflict",
        ),
        primary_skills=("oh-my-hermes", "voice-operator", "gateway-intent-card"),
        primary_harnesses=("routing", "chat-wrapper"),
        wrapper_actions=("ask_followup", "show_status", "route_request"),
        evidence_boundary="A guide role can choose or explain a route; it is not plan acceptance, dispatch, execution, review, CI, or merge evidence.",
        legacy_ids=("hybrid-guidance", "retained-router"),
    ),
    RoleDefinition(
        id="researcher",
        title="Researcher",
        purpose="Own source-backed discovery and keep evidence, inference, confidence, freshness, and unknowns separate.",
        owns=(
            "Research question and source boundary",
            "Observed evidence versus inferred trend",
            "Research summary that can feed planning or strategy",
        ),
        primary_skills=("web-research", "best-practice-research", "research-brief", "autoresearch-goal"),
        primary_harnesses=("research", "business-research"),
        wrapper_actions=("ask_followup", "show_sources", "show_status"),
        evidence_boundary="A researcher role can prepare or summarize evidence; it is not implementation, review, CI, or merge evidence.",
        legacy_ids=("research-lead",),
    ),
    RoleDefinition(
        id="planner",
        title="Planner",
        purpose="Own clarification, non-goals, acceptance criteria, tradeoffs, loopability, and verification strategy.",
        owns=(
            "One-question clarification when scope is ambiguous",
            "Plan artifact with goals, non-goals, risks, and verification",
            "Decision gate before handoff or execution",
        ),
        primary_skills=("deep-interview", "plan", "ralplan", "loop"),
        primary_harnesses=("deep-interview", "planning", "strategy-synthesis", "goal-loop"),
        wrapper_actions=("ask_followup", "accept_plan", "revise_plan", "show_status"),
        evidence_boundary="A planner role can make work reviewable; it is not proof that the work was accepted or executed.",
        legacy_ids=("planning-lead",),
    ),
    RoleDefinition(
        id="operator",
        title="Operator",
        purpose="Own non-coding company, product, delivery, meeting, material, and scheduled operations workflows.",
        owns=(
            "Business workflow cards and operating records",
            "Meeting, strategy, feedback, reliability, report, and material package preparation",
            "Delivery or automation state only when observed by a wrapper or host",
        ),
        primary_skills=(
            "feedback-triage",
            "meeting-brief",
            "strategy-brief",
            "automation-blueprint",
            "materials-package",
            "report-package",
            "reliability-review",
            "idea-to-deploy",
            "deploy-and-monitor",
            "cto-loop",
            "operating-rhythm",
            "ops-review",
            "deliverable-package",
            "github-event-ops",
        ),
        primary_harnesses=("business-research", "customer-insight-triage", "meeting-facilitation", "materials-package", "operations"),
        wrapper_actions=("show_status", "prepare_handoff", "refresh_status"),
        evidence_boundary="An operator role can prepare operational workflow guidance; it is not meeting completion, file export, delivery, deploy, monitoring, or external platform evidence.",
        legacy_ids=("retained-operator",),
    ),
    RoleDefinition(
        id="memory-keeper",
        title="Memory Keeper",
        purpose="Own durable context review, project knowledge capture, stale memory warnings, and safe memory update handoffs.",
        owns=(
            "Memory and wiki context review",
            "Stale, duplicate, or conflicting context candidates",
            "Human-approved context pack preparation",
        ),
        primary_skills=("wiki", "memory-sync"),
        primary_harnesses=("knowledge", "memory-context-review"),
        wrapper_actions=("ask_followup", "show_status", "prepare_handoff"),
        evidence_boundary="A memory keeper role can prepare context changes; it is not proof that Hermes internal memory, USER.md, MEMORY.md, wiki, or skill files were changed.",
        legacy_ids=("retained-knowledge",),
    ),
    RoleDefinition(
        id="handoff-guide",
        title="Handoff Guide",
        purpose="Own executor/runtime selection, prepared handoff payloads, and status narration while the chosen coding agent or runtime owns code changes.",
        owns=(
            "Executor, runtime, or Hermes coding-skill choice",
            "Prepared coding handoff with team/swarm, worker, worktree, acceptance, and verification expectations when relevant",
            "Observed lifecycle status when a tested executor contract records it",
        ),
        primary_skills=("ultragoal", "ultrawork", "ralph", "ai-slop-cleaner"),
        primary_harnesses=("goal-execution", "parallel-delivery", "coding-handling"),
        wrapper_actions=("choose_executor", "show_prompt_handoff", "show_runtime_handoff", "start_team", "start_swarm", "prepare_worktree", "send_to_executor", "show_status"),
        evidence_boundary="A prepared coding handoff is not executor/runtime dispatch, worker start, worktree creation, result, verification, review, CI, merge readiness, or merge evidence. Hermes/OMX/OMO/OMC runtime handoffs must record separate `runtime_observation/v1` events before the status can move from prepared to observed.",
        legacy_ids=("coding-handoff", "runtime-handoff-guidance", "codex-handoff-guidance"),
    ),
    RoleDefinition(
        id="builder",
        title="Builder",
        purpose="Name the implementation responsibility inside a prepared Hermes-facing playbook while the selected executor/runtime remains the actual work owner.",
        owns=(
            "Presentation-layer implementation step in the prepared playbook",
            "selected executor/runtime ownership narration",
            "Expected implementation artifact boundary before observed evidence exists",
        ),
        primary_skills=("ultragoal", "ultrawork", "ralph"),
        primary_harnesses=("goal-execution", "coding-handling"),
        wrapper_actions=("choose_executor", "show_prompt_handoff", "show_runtime_handoff", "send_to_executor", "show_status"),
        evidence_boundary="A builder role label is not hidden coding execution, executor/runtime dispatch, worker start, implementation result, verification, review, CI, merge readiness, or merge evidence. The selected executor/runtime owns implementation only after observed evidence exists.",
        legacy_ids=("implementation-owner",),
    ),
    RoleDefinition(
        id="tracker",
        title="Tracker",
        purpose="Own runtime status, target topology, executor session, measurement, tool readiness, and observability narration.",
        owns=(
            "Observed runtime, target, executor, and status-card state",
            "Tool, MCP, credential, token, cost, latency, and run-history readiness gaps",
            "Progress narration without upgrading missing evidence",
        ),
        primary_skills=("performance-goal", "agent-board", "executor-runtime-readiness", "toolbelt-readiness", "ops-observability-card", "doctor", "skill", "cancel"),
        primary_harnesses=("measurement", "status", "tool-readiness", "operator-health"),
        wrapper_actions=("show_status", "refresh_status", "choose_executor"),
        evidence_boundary="A tracker role can report status and missing evidence; it is not proof that an executor, worker, tool, MCP server, CI job, or platform action ran.",
        legacy_ids=("hybrid-measurement",),
    ),
    RoleDefinition(
        id="reviewer",
        title="Reviewer",
        purpose="Own claim checking, review findings, QA framing, release/readiness review, and evidence requirements.",
        owns=(
            "Findings and risks",
            "Verification, CI, and release-readiness status",
            "Follow-up handoff only when fixes are accepted",
        ),
        primary_skills=("code-review", "ultraqa", "ask"),
        primary_harnesses=("code-review", "qa", "ops-review"),
        wrapper_actions=("show_findings", "prepare_fix_handoff", "refresh_status"),
        evidence_boundary="Review findings are not fix evidence; merge-ready is not merged.",
        legacy_ids=("review-gate", "hybrid-review", "hybrid-verification"),
    ),
)


def role_definitions() -> tuple[RoleDefinition, ...]:
    return _ROLES


def role_surface_payload() -> dict[str, object]:
    return {
        "schema_version": ROLE_CONTRACT_VERSION,
        "runtime_claim": "roles_are_descriptors_not_runtime_agents",
        "roles": [role.to_dict() for role in _ROLES],
    }


def role_summary_markdown() -> str:
    lines = [
        "OMH role names are responsibility descriptors, not runtime agents. They help Hermes and wrappers explain who owns the next step without implying a hidden worker ran.",
        "",
    ]
    for role in _ROLES:
        lines.extend(
            [
                f"- `{role.id}` ({role.title}): {role.purpose}",
                f"  - Aliases: {', '.join(f'`{alias}`' for alias in role.legacy_ids) if role.legacy_ids else '`none`'}",
                f"  - Skills: {', '.join(f'`{skill}`' for skill in role.primary_skills)}",
                f"  - Evidence boundary: {role.evidence_boundary}",
            ]
        )
    return "\n".join(lines)


def role_file_markdown(role: RoleDefinition) -> str:
    return "\n".join(
        [
            f"# {role.title}",
            "",
            "This OMH role is a responsibility descriptor, not a runtime agent.",
            "",
            role.purpose,
            "",
            "## OMH Role Context",
            "",
            ROLE_WORKFLOW_CONTEXT_RULE,
            "",
            ROLE_CHAT_RULE,
            "",
            ROLE_BOUNDARY_RULE,
            "",
            "## Legacy Aliases",
            "",
            *([f"- `{item}`" for item in role.legacy_ids] if role.legacy_ids else ["- none"]),
            "",
            "## Owns",
            "",
            *[f"- {item}" for item in role.owns],
            "",
            "## Primary Skills",
            "",
            *[f"- `{item}`" for item in role.primary_skills],
            "",
            "## Primary Harnesses",
            "",
            *[f"- `{item}`" for item in role.primary_harnesses],
            "",
            "## Wrapper Actions",
            "",
            *[f"- `{item}`" for item in role.wrapper_actions],
            "",
            "## Evidence Boundary",
            "",
            role.evidence_boundary,
            "",
        ]
    )


def roles_reference_markdown() -> str:
    lines = [
        "# OMH Role Surface",
        "",
        "OMH roles are responsibility descriptors, not runtime agents. They make chat responses, wrapper buttons, and status cards easier to read without claiming that a separate worker exists or ran.",
        "",
        "Use roles inside the flagship `request-to-handoff` path:",
        "",
        "`plain request -> responsible role -> plan/status/handoff action -> observed evidence boundary`",
        "",
        "## Skills, Specialists, Roles, Harnesses, and Executors",
        "",
        "These terms have separate jobs. A **skill** is a reusable workflow entry point. A **specialist** is a prepared task-phase expertise profile that selects eligible skills, critique checkpoints, repeat-validation expectations, and claim-integrity rules. A **role** is the human-readable responsibility label used in chat. A **harness** is the quality and evidence contract. An **executor** is the selected runtime owner that may actually perform work.",
        "",
        "A specialist is not another command for normal users and is not a hidden agent. Its prepared coverage percentage measures whether the work plan contains the required stages; its observed goal-achievement percentage remains zero until matching current evidence is recorded. Prepared coverage, self-reports, stale evidence, or evidence bound to another goal/skill/plan cannot raise observed achievement.",
        "",
        "## OMH Role Context",
        "",
        ROLE_WORKFLOW_CONTEXT_RULE,
        "",
        ROLE_CHAT_RULE,
        "",
        ROLE_BOUNDARY_RULE,
        "",
        "## Operating Models",
        "",
        "Operating models are lighter than role profile packs. They can record an",
        "advanced default Hermes collaboration posture for a specific profile, but normal",
        "setup does not force users to choose one and they do not install role files or",
        "claim that separate agents ran.",
        "",
        "| ID | Default posture |",
        "| --- | --- |",
        "| `solo-operator` | Keep the safest single-operator defaults and ask before executor dispatch. |",
        "| `small-team` | Bias chat narration toward product, technical, QA, and release ownership without installing team files. |",
        "| `research-ops` | Keep Hermes focused on research, strategy, and meeting workflows. |",
        "| `coding-runtime-team` | Make selected Hermes/OMX/OMO/OMC runtime handoffs and observed runtime ladder status first-class. |",
        "",
        "Use `omh setup --operating-model <id>` only when a profile should start from one",
        "of these postures. Use `omh setup --profile-pack <id>` only when you also want",
        "visible role files under Hermes.",
        "",
        "An operating model is an organization pattern for Hermes chat, not proof that",
        "any worker or executor ran. The map below shows where roles shape chat routing,",
        "prepared handoffs, and observed evidence:",
        "",
        '<p align="center">',
        '  <img src="../assets/omh-profile-interaction-map.svg" alt="OMH request-to-handoff role interaction map" width="920">',
        "</p>",
        "",
        "## Roles",
        "",
    ]
    for role in _ROLES:
        lines.extend(
            [
                f"### {role.title}",
                "",
                f"- ID: `{role.id}`",
                f"- Display name: {role.title}",
                f"- Legacy aliases: {', '.join(f'`{alias}`' for alias in role.legacy_ids) if role.legacy_ids else '`none`'}",
                f"- Purpose: {role.purpose}",
                "- Owns:",
                *[f"  - {item}" for item in role.owns],
                f"- Primary skills: {', '.join(f'`{skill}`' for skill in role.primary_skills)}",
                f"- Primary harnesses: {', '.join(f'`{harness}`' for harness in role.primary_harnesses)}",
                f"- Wrapper actions: {', '.join(f'`{action}`' for action in role.wrapper_actions)}",
                f"- Evidence boundary: {role.evidence_boundary}",
                *_hermes_coding_harness_role_note(role.id),
                "",
            ]
        )
    lines.extend(
        [
            "## Public Claim Rule",
            "",
            "A role can explain responsibility and next action. A role does not prove execution, dispatch, review, CI, merge readiness, or merge evidence. Those claims require matching observed runtime or wrapper evidence.",
            "",
        ]
    )
    return "\n".join(lines)


def _hermes_coding_harness_role_note(role_id: str) -> list[str]:
    notes = {
        "handoff-guide": (
            "- Hermes coding harness: When Hermes is the selected coding owner, read",
            "  `hermes_coding_harness/v1` before answering status questions. The Handoff",
            "  Guide should name the current stage, lane owner, next action, and missing",
            "  evidence without claiming PR creation, review, CI, merge readiness, or merge.",
        ),
        "builder": (
            "- Hermes coding harness: In Hermes-owned coding work, the builder lane is one",
            "  lane inside `hermes_coding_harness/v1`. It can be prepared or pending without",
            "  proving that implementation happened.",
        ),
        "reviewer": (
            "- Hermes coding harness: In Hermes-owned coding work, the reviewer lane upgrades",
            "  only after observed review evidence. A prepared review gate is not review",
            "  passed.",
        ),
    }
    return list(notes.get(role_id, ()))
