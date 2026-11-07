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
    "R-RETIRED-SIBLING-FOLD": (
        "A skill retired into a sibling (#1691) keeps its trigger table as the record of what the contract answered to, "
        "and the sibling carries the same phrase because the fold moved it there. Only one of the two owners is routable: "
        "the retired contract's projections are `(\"workflow_reference\",)`, so it cannot win a route and the shared "
        "identity is not an ambiguity a user can reach. The sharing has to end together with the retirement -- un-retiring "
        "the contract restores a real two-owner collision, and this declaration is what makes the gate say so."
    ),
    "R-OMH-ENTRYPOINT": (
        "The `/omh` entrypoint token is the meta-router's job to detect and the router skill's job to describe; both must answer to it."
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
    "R-RELEASE-READINESS": (
        "Release readiness is both an executive loop question and a production-audit subject."
    ),
    "R-RENDER-QA": (
        "Render QA covers both produced material packages and on-screen visual verification."
    ),
    "R-CHAT-GATEWAY": (
        "Chat gateway platform names belong to both automation blueprints and gateway intent cards."
    ),
    "R-SPEND-BESIDE-MONEY": (
        "Booking and sending are automation-blueprint's scheduling words and, said of the person's money, a spend. "
        "spend-gate scores them only inside a Korean request its own admission rule admitted (a spend, or a booking or a send "
        "of the person's money), so a booking or a send without the person's money never reaches the gate through them. "
        "Inside an admitted request they add to the gate's score like its other phrases, and either skill may still win."
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
    CollisionDeclaration(identity="autoresearch-goal", owners=("autoresearch-goal", "research",), rationale_id="R-RETIRED-SIBLING-FOLD"),
    CollisionDeclaration(identity="benchmark", owners=("performance-goal", "ultraperf",), rationale_id="R-RETIRED-SIBLING-FOLD"),
    CollisionDeclaration(identity="best practice", owners=("best-practice-research", "web-research",), rationale_id="R-RETIRED-SIBLING-FOLD"),
    CollisionDeclaration(identity="best-practice-research", owners=("best-practice-research", "web-research",), rationale_id="R-RETIRED-SIBLING-FOLD"),
    CollisionDeclaration(identity="broken layout", owners=("frontend", "visual-qa",), rationale_id="R-LAYOUT-DEFECT-INTAKE"),
    CollisionDeclaration(identity="check the docs", owners=("best-practice-research", "web-research",), rationale_id="R-RETIRED-SIBLING-FOLD"),
    CollisionDeclaration(identity="ci failed", owners=("build-failure-triage", "github-event-ops",), rationale_id="R-CI-FAILURE-INTAKE"),
    CollisionDeclaration(identity="ci 실패", owners=("build-failure-triage", "github-event-ops",), rationale_id="R-CI-FAILURE-INTAKE"),
    CollisionDeclaration(identity="coding handoff", owners=("maestro", "plan",), rationale_id="R-CODING-HANDOFF-INTAKE"),
    CollisionDeclaration(identity="coordinated workers", owners=("team", "ultrawork",), rationale_id="R-PARALLEL-EXECUTION"),
    CollisionDeclaration(identity="critic research", owners=("autoresearch-goal", "research",), rationale_id="R-RETIRED-SIBLING-FOLD"),
    CollisionDeclaration(identity="delivery process", owners=("ultraprocess", "ultrawork",), rationale_id="R-DELIVERY-CYCLE"),
    CollisionDeclaration(identity="durable research", owners=("autoresearch-goal", "research",), rationale_id="R-RETIRED-SIBLING-FOLD"),
    CollisionDeclaration(identity="end-to-end process", owners=("ultraprocess", "ultrawork",), rationale_id="R-DELIVERY-CYCLE"),
    CollisionDeclaration(identity="feedback trends", owners=("feedback-triage", "research-brief",), rationale_id="R-FEEDBACK-SIGNAL"),
    CollisionDeclaration(identity="finish until done", owners=("ralph", "ultrawork",), rationale_id="R-PERSISTENT-EXECUTION"),
    CollisionDeclaration(identity="generated file", owners=("deliverable-package", "verification-gate",), rationale_id="R-GENERATED-FILE-SENSE"),
    CollisionDeclaration(identity="issue triage", owners=("github-event-ops", "plan",), rationale_id="R-ISSUE-INTAKE"),
    CollisionDeclaration(identity="latency", owners=("performance-goal", "ultraperf",), rationale_id="R-RETIRED-SIBLING-FOLD"),
    CollisionDeclaration(identity="layout broken", owners=("frontend", "visual-qa",), rationale_id="R-LAYOUT-DEFECT-INTAKE"),
    CollisionDeclaration(identity="make a pr", owners=("ultraprocess", "ultrawork",), rationale_id="R-DELIVERY-CYCLE"),
    CollisionDeclaration(identity="official docs", owners=("best-practice-research", "web-research",), rationale_id="R-RETIRED-SIBLING-FOLD"),
    CollisionDeclaration(identity="one-cycle delivery", owners=("ultraprocess", "ultrawork",), rationale_id="R-DELIVERY-CYCLE"),
    CollisionDeclaration(identity="open a pr", owners=("ultraprocess", "ultrawork",), rationale_id="R-DELIVERY-CYCLE"),
    CollisionDeclaration(identity="performance goal", owners=("performance-goal", "ultraperf",), rationale_id="R-RETIRED-SIBLING-FOLD"),
    CollisionDeclaration(identity="performance-goal", owners=("performance-goal", "ultraperf",), rationale_id="R-RETIRED-SIBLING-FOLD"),
    CollisionDeclaration(identity="persistent execution", owners=("ralph", "ultrawork",), rationale_id="R-PERSISTENT-EXECUTION"),
    CollisionDeclaration(identity="plan implement review docs pr", owners=("ultraprocess", "ultrawork",), rationale_id="R-DELIVERY-CYCLE"),
    CollisionDeclaration(identity="pr-ready", owners=("ultraprocess", "ultrawork",), rationale_id="R-DELIVERY-CYCLE"),
    CollisionDeclaration(identity="prepare a pr", owners=("ultraprocess", "ultrawork",), rationale_id="R-DELIVERY-CYCLE"),
    CollisionDeclaration(identity="release readiness", owners=("cto-loop", "production-audit",), rationale_id="R-RELEASE-READINESS"),
    CollisionDeclaration(identity="render qa", owners=("materials-package", "visual-qa",), rationale_id="R-RENDER-QA"),
    CollisionDeclaration(identity="research goal", owners=("autoresearch-goal", "research",), rationale_id="R-RETIRED-SIBLING-FOLD"),
    CollisionDeclaration(identity="research plan implement review docs pr", owners=("ultraprocess", "ultrawork",), rationale_id="R-DELIVERY-CYCLE"),
    CollisionDeclaration(identity="single-cycle delivery", owners=("ultraprocess", "ultrawork",), rationale_id="R-DELIVERY-CYCLE"),
    CollisionDeclaration(identity="throughput", owners=("performance-goal", "ultraperf",), rationale_id="R-RETIRED-SIBLING-FOLD"),
    CollisionDeclaration(identity="upstream guidance", owners=("best-practice-research", "web-research",), rationale_id="R-RETIRED-SIBLING-FOLD"),
    CollisionDeclaration(identity="what do the docs say", owners=("best-practice-research", "web-research",), rationale_id="R-RETIRED-SIBLING-FOLD"),
    CollisionDeclaration(identity="고객 피드백", owners=("feedback-triage", "research",), rationale_id="R-FEEDBACK-SIGNAL"),
    CollisionDeclaration(identity="디스코드", owners=("automation-blueprint", "gateway-intent-card",), rationale_id="R-CHAT-GATEWAY"),
    CollisionDeclaration(identity="레이아웃 깨짐", owners=("frontend", "visual-qa",), rationale_id="R-LAYOUT-DEFECT-INTAKE"),
    CollisionDeclaration(identity="보내", owners=("automation-blueprint", "spend-gate",), rationale_id="R-SPEND-BESIDE-MONEY"),
    CollisionDeclaration(identity="서브에이전트", owners=("agent-board", "executor-runtime-readiness",), rationale_id="R-SUBAGENT-VIEW"),
    CollisionDeclaration(identity="슬랙", owners=("automation-blueprint", "gateway-intent-card",), rationale_id="R-CHAT-GATEWAY"),
    CollisionDeclaration(identity="예약", owners=("automation-blueprint", "spend-gate",), rationale_id="R-SPEND-BESIDE-MONEY"),
    CollisionDeclaration(identity="장기 목표", owners=("loop", "ultragoal",), rationale_id="R-LONG-HORIZON-GOAL"),
    CollisionDeclaration(identity="조용히", owners=("automation-blueprint", "gateway-intent-card",), rationale_id="R-CHAT-GATEWAY"),
    CollisionDeclaration(identity="출시 준비", owners=("cto-loop", "production-audit",), rationale_id="R-RELEASE-READINESS"),
    CollisionDeclaration(identity="텔레그램", owners=("automation-blueprint", "gateway-intent-card",), rationale_id="R-CHAT-GATEWAY"),
)
