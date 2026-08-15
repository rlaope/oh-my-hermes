from __future__ import annotations

from typing import Any


ROUTE_DECISION_SCHEMA_VERSION = "route_decision/v1"


def build_route_decision_contract(decision: dict[str, Any]) -> dict[str, Any]:
    """Return the stable, privacy-safe routing contract shared by consumers.

    The legacy route payload remains unchanged. This compact object gives
    telemetry, hooks, wrappers, and runtime artifacts one common shape without
    copying prompts or other user content.
    """
    recommendations = decision.get("recommendations", [])
    compact_candidates: list[dict[str, Any]] = []
    # Keep the shared contract compact enough for messenger interaction budgets;
    # the legacy route payload retains the full recommendation list.
    for recommendation in recommendations[:2] if isinstance(recommendations, list) else []:
        if not isinstance(recommendation, dict):
            continue
        compact_candidates.append(
            {
                "skill": str(recommendation.get("skill", "")),
            }
        )

    scores = [
        int(recommendation.get("score", 0))
        for recommendation in recommendations[:2]
        if isinstance(recommendations, list) and isinstance(recommendation, dict)
    ]
    margin = scores[0] - scores[1] if len(scores) > 1 else None
    action = str(decision.get("action", "fallback"))
    explicit = bool(decision.get("explicit", False))
    if explicit:
        router_stage = "explicit"
    elif action == "fallback":
        router_stage = "fallback"
    elif bool(decision.get("ambiguous", False)):
        router_stage = "candidate_handoff"
    elif any(
        "guard:" in str(item)
        for candidate in recommendations[:2]
        if isinstance(recommendations, list)
        for item in candidate.get("matched", [])
        if isinstance(candidate, dict)
    ):
        router_stage = "guarded"
    else:
        router_stage = "recommendation"

    reason = str(decision.get("reason", ""))
    if len(reason) > 16:
        reason = f"{reason[:13].rstrip()}..."

    contract = {
        "schema_version": ROUTE_DECISION_SCHEMA_VERSION,
        "router_stage": router_stage,
        "action": action,
        "selected_skill": str(decision.get("selected_skill", "oh-my-hermes")),
        "selected_harness": str(decision.get("selected_harness", "coding-handling")),
        "confidence": str(decision.get("confidence", "low")),
    }
    if len(compact_candidates) > 1:
        contract["candidates"] = compact_candidates
    if explicit:
        contract["explicit"] = True
    if bool(decision.get("ambiguous", False)):
        contract["ambiguous"] = True
    if action == "fallback":
        contract["fallback"] = True
    if router_stage in {"guarded", "candidate_handoff", "fallback"} or action != "dispatch":
        contract["reason"] = reason
    if margin is not None:
        contract["margin"] = margin
    threshold = str(decision.get("threshold", "high"))
    if threshold != contract["confidence"]:
        contract["threshold"] = threshold
    return contract
