from __future__ import annotations

from dataclasses import dataclass


ROLE_CONTRACT_VERSION = "omh_role_surface/v1"


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

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "purpose": self.purpose,
            "owns": list(self.owns),
            "primary_skills": list(self.primary_skills),
            "primary_harnesses": list(self.primary_harnesses),
            "wrapper_actions": list(self.wrapper_actions),
            "evidence_boundary": self.evidence_boundary,
            "runtime_claim": "descriptor_not_runtime_agent",
        }


_ROLES = (
    RoleDefinition(
        id="research-lead",
        title="Research Lead",
        purpose="Own source-backed discovery and keep evidence, inference, confidence, and unknowns separate.",
        owns=(
            "Research question and source boundary",
            "Observed evidence versus inferred trend",
            "Research summary that can feed planning or strategy",
        ),
        primary_skills=("web-research", "best-practice-research", "research-brief", "autoresearch-goal"),
        primary_harnesses=("research", "business-research"),
        wrapper_actions=("ask_followup", "show_sources", "show_status"),
        evidence_boundary="A research role can prepare or summarize evidence; it is not implementation, review, CI, or merge evidence.",
    ),
    RoleDefinition(
        id="planning-lead",
        title="Planning Lead",
        purpose="Own clarification, non-goals, acceptance criteria, tradeoffs, and verification strategy.",
        owns=(
            "One-question clarification when scope is ambiguous",
            "Plan artifact with goals, non-goals, risks, and verification",
            "Decision gate before handoff or execution",
        ),
        primary_skills=("deep-interview", "plan", "ralplan", "strategy-brief"),
        primary_harnesses=("deep-interview", "planning", "strategy-synthesis"),
        wrapper_actions=("ask_followup", "accept_plan", "revise_plan", "show_status"),
        evidence_boundary="A planning role can make work reviewable; it is not proof that the work was accepted or executed.",
    ),
    RoleDefinition(
        id="review-gate",
        title="Review Gate",
        purpose="Own claim checking, release/readiness review, QA framing, and evidence requirements.",
        owns=(
            "Findings and risks",
            "Verification, CI, and release-readiness status",
            "Follow-up handoff only when fixes are accepted",
        ),
        primary_skills=("code-review", "ultraqa", "ops-review"),
        primary_harnesses=("code-review", "qa", "ops-review"),
        wrapper_actions=("show_findings", "prepare_fix_handoff", "refresh_status"),
        evidence_boundary="Review findings are not fix evidence; merge-ready is not merged.",
    ),
    RoleDefinition(
        id="coding-handoff",
        title="Coding Handoff",
        purpose="Own executor/runtime selection, prepared handoff payloads, and status narration while the chosen coding agent or runtime owns code changes.",
        owns=(
            "Executor, runtime, or Hermes coding-skill choice",
            "Prepared coding handoff with team/swarm, worker, worktree, acceptance, and verification expectations when relevant",
            "Observed lifecycle status when a tested executor contract records it",
        ),
        primary_skills=("ultragoal", "ultrawork", "ralph", "ai-slop-cleaner"),
        primary_harnesses=("goal-execution", "parallel-delivery", "coding-handling"),
        wrapper_actions=("choose_executor", "show_prompt_handoff", "show_runtime_handoff", "start_team", "start_swarm", "prepare_worktree", "send_to_executor", "show_status"),
        evidence_boundary="A prepared coding handoff is not executor/runtime dispatch, worker start, worktree creation, result, verification, review, CI, merge readiness, or merge evidence.",
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
        "## Roles",
        "",
    ]
    for role in _ROLES:
        lines.extend(
            [
                f"### {role.title}",
                "",
                f"- ID: `{role.id}`",
                f"- Purpose: {role.purpose}",
                "- Owns:",
                *[f"  - {item}" for item in role.owns],
                f"- Primary skills: {', '.join(f'`{skill}`' for skill in role.primary_skills)}",
                f"- Primary harnesses: {', '.join(f'`{harness}`' for harness in role.primary_harnesses)}",
                f"- Wrapper actions: {', '.join(f'`{action}`' for action in role.wrapper_actions)}",
                f"- Evidence boundary: {role.evidence_boundary}",
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
