"""Approved trigger-collision declarations.

Each entry records that a maintainer looked at one normalized trigger identity
shared by two or more skills and judged the sharing intentional. A declaration
carries only the normalized identity, the exact owner set that was reviewed,
and a rationale ID -- never the trigger phrases themselves, so this file cannot
become a second source of truth about what a skill routes on.

`validate_collision_declarations()` in `trigger_review.py` fails closed on an
undeclared group, on a declaration whose group no longer collides, and on a
group whose owner set grew beyond what was approved. Adding a trigger that
collides with another skill's trigger or alias is not a defect; it just has to
be reviewed here first.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CollisionDeclaration:
    """An approval record for one normalized collision group.

    It stores only the normalized identity, the exact owner set that was
    reviewed, and a rationale ID. It deliberately does NOT restate the trigger
    phrases themselves: the catalog stays the single source of truth, and a
    declaration cannot drift into a competing definition of what a skill routes
    on.
    """

    identity: str
    owners: tuple[str, ...]
    rationale_id: str

# Why each family of shared identities is intentional. The IDs are stable so a
# reviewer can find every group approved for the same reason.
COLLISION_RATIONALES: dict[str, str] = {
    "R-OMH-ENTRYPOINT": (
        "The `/omh` entrypoint token is the meta-router's job to detect and the router skill's job to describe; both must answer to it."
    ),
    "R-ACCESSIBILITY-SURFACE": (
        "Accessibility is a real concern of both the visual frontend surface and the voice operator surface."
    ),
    "R-GENERATED-FILE-SENSE": (
        "A generated file is two things: the PDF somebody produced and wants attached, which is the delivery lane's, and a checked-in artifact whose source of truth is a generator, which is the verification gate's. The words are identical and the sense is decided by whether the sentence also asks where the file came from, so both own the phrase and `generated_artifact_provenance_before_deliverable_package` separates them."
    ),
    "R-LAYOUT-DEFECT-INTAKE": (
        "A reported broken layout is legitimately either a frontend fix or a visual-QA verification request."
    ),
    "R-CI-FAILURE-INTAKE": (
        "A CI failure is both a build-triage subject and a GitHub event to operate on."
    ),
    "R-PARALLEL-EXECUTION": (
        "Coordinated parallel workers are the shared vocabulary of team orchestration and ultrawork fan-out."
    ),
    "R-DELIVERY-CYCLE": (
        "End-to-end delivery through a PR is the overlapping promise of the process and ultrawork engines."
    ),
    "R-FEEDBACK-SIGNAL": (
        "Customer feedback is both a triage input and a research subject."
    ),
    "R-PERSISTENT-EXECUTION": (
        "Run-until-done persistence is the defining behavior of ralph and a mode of ultrawork."
    ),
    "R-ISSUE-INTAKE": (
        "Issue triage is both a GitHub operation and a planning intake."
    ),
    "R-ENVIRONMENT-INVENTORY": (
        "MCP inventory is read by both the harness session view and the workspace audit."
    ),
    "R-RELEASE-GATE": (
        "A release gate is enforced by the verification gate and inspected during code review."
    ),
    "R-RELEASE-READINESS": (
        "Release readiness is both an executive loop question and a production-audit subject."
    ),
    "R-RENDER-QA": (
        "Render QA covers both produced material packages and on-screen visual verification."
    ),
    "R-CHAT-GATEWAY": (
        "Chat gateway platform names belong to both automation blueprints and gateway intent cards."
    ),
    "R-SUBAGENT-VIEW": (
        "Subagent state is shown by the agent board and assessed by executor runtime readiness."
    ),
    "R-LONG-HORIZON-GOAL": (
        "A long-horizon goal is owned by the goal engine and driven by the loop engine."
    ),
    "R-CODING-HANDOFF-INTAKE": (
        "A coding handoff request is both plan's general request-shaping vocabulary and maestro's own "
        "handoff-preparation mechanic."
    ),
}

INTENTIONAL_COLLISIONS: tuple[CollisionDeclaration, ...] = (
    CollisionDeclaration(identity="./omh", owners=("meta-router", "oh-my-hermes",), rationale_id="R-OMH-ENTRYPOINT"),
    CollisionDeclaration(identity="/omh", owners=("meta-router", "oh-my-hermes",), rationale_id="R-OMH-ENTRYPOINT"),
    CollisionDeclaration(identity="accessibility", owners=("frontend", "voice-operator",), rationale_id="R-ACCESSIBILITY-SURFACE"),
    CollisionDeclaration(identity="broken layout", owners=("frontend", "visual-qa",), rationale_id="R-LAYOUT-DEFECT-INTAKE"),
    CollisionDeclaration(identity="ci failed", owners=("build-failure-triage", "github-event-ops",), rationale_id="R-CI-FAILURE-INTAKE"),
    CollisionDeclaration(identity="ci 실패", owners=("build-failure-triage", "github-event-ops",), rationale_id="R-CI-FAILURE-INTAKE"),
    CollisionDeclaration(identity="coding handoff", owners=("maestro", "plan",), rationale_id="R-CODING-HANDOFF-INTAKE"),
    CollisionDeclaration(identity="coordinated workers", owners=("team", "ultrawork",), rationale_id="R-PARALLEL-EXECUTION"),
    CollisionDeclaration(identity="delivery process", owners=("ultraprocess", "ultrawork",), rationale_id="R-DELIVERY-CYCLE"),
    CollisionDeclaration(identity="end-to-end process", owners=("ultraprocess", "ultrawork",), rationale_id="R-DELIVERY-CYCLE"),
    CollisionDeclaration(identity="feedback trends", owners=("feedback-triage", "research-brief",), rationale_id="R-FEEDBACK-SIGNAL"),
    CollisionDeclaration(identity="finish until done", owners=("ralph", "ultrawork",), rationale_id="R-PERSISTENT-EXECUTION"),
    CollisionDeclaration(identity="generated file", owners=("deliverable-package", "verification-gate",), rationale_id="R-GENERATED-FILE-SENSE"),
    CollisionDeclaration(identity="issue triage", owners=("github-event-ops", "plan",), rationale_id="R-ISSUE-INTAKE"),
    CollisionDeclaration(identity="layout broken", owners=("frontend", "visual-qa",), rationale_id="R-LAYOUT-DEFECT-INTAKE"),
    CollisionDeclaration(identity="make a pr", owners=("ultraprocess", "ultrawork",), rationale_id="R-DELIVERY-CYCLE"),
    CollisionDeclaration(identity="mcp inventory", owners=("harness-session-inventory", "workspace-audit",), rationale_id="R-ENVIRONMENT-INVENTORY"),
    CollisionDeclaration(identity="one-cycle delivery", owners=("ultraprocess", "ultrawork",), rationale_id="R-DELIVERY-CYCLE"),
    CollisionDeclaration(identity="open a pr", owners=("ultraprocess", "ultrawork",), rationale_id="R-DELIVERY-CYCLE"),
    CollisionDeclaration(identity="persistent execution", owners=("ralph", "ultrawork",), rationale_id="R-PERSISTENT-EXECUTION"),
    CollisionDeclaration(identity="plan implement review docs pr", owners=("ultraprocess", "ultrawork",), rationale_id="R-DELIVERY-CYCLE"),
    CollisionDeclaration(identity="pr-ready", owners=("ultraprocess", "ultrawork",), rationale_id="R-DELIVERY-CYCLE"),
    CollisionDeclaration(identity="prepare a pr", owners=("ultraprocess", "ultrawork",), rationale_id="R-DELIVERY-CYCLE"),
    CollisionDeclaration(identity="release gate", owners=("code-review", "verification-gate",), rationale_id="R-RELEASE-GATE"),
    CollisionDeclaration(identity="release readiness", owners=("cto-loop", "production-audit",), rationale_id="R-RELEASE-READINESS"),
    CollisionDeclaration(identity="render qa", owners=("materials-package", "visual-qa",), rationale_id="R-RENDER-QA"),
    CollisionDeclaration(identity="research plan implement review docs pr", owners=("ultraprocess", "ultrawork",), rationale_id="R-DELIVERY-CYCLE"),
    CollisionDeclaration(identity="single-cycle delivery", owners=("ultraprocess", "ultrawork",), rationale_id="R-DELIVERY-CYCLE"),
    CollisionDeclaration(identity="고객 피드백", owners=("feedback-triage", "research",), rationale_id="R-FEEDBACK-SIGNAL"),
    CollisionDeclaration(identity="디스코드", owners=("automation-blueprint", "gateway-intent-card",), rationale_id="R-CHAT-GATEWAY"),
    CollisionDeclaration(identity="레이아웃 깨짐", owners=("frontend", "visual-qa",), rationale_id="R-LAYOUT-DEFECT-INTAKE"),
    CollisionDeclaration(identity="서브에이전트", owners=("agent-board", "executor-runtime-readiness",), rationale_id="R-SUBAGENT-VIEW"),
    CollisionDeclaration(identity="슬랙", owners=("automation-blueprint", "gateway-intent-card",), rationale_id="R-CHAT-GATEWAY"),
    CollisionDeclaration(identity="장기 목표", owners=("loop", "ultragoal",), rationale_id="R-LONG-HORIZON-GOAL"),
    CollisionDeclaration(identity="접근성", owners=("frontend", "voice-operator",), rationale_id="R-ACCESSIBILITY-SURFACE"),
    CollisionDeclaration(identity="조용히", owners=("automation-blueprint", "gateway-intent-card",), rationale_id="R-CHAT-GATEWAY"),
    CollisionDeclaration(identity="출시 준비", owners=("cto-loop", "production-audit",), rationale_id="R-RELEASE-READINESS"),
    CollisionDeclaration(identity="텔레그램", owners=("automation-blueprint", "gateway-intent-card",), rationale_id="R-CHAT-GATEWAY"),
)
