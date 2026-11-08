"""A route with the skills of turned-off capability families taken out.

`omh capability-policy disable <family>` stops a family's tools; this is the
router's half. Given the skills an OMH home turned off (`disabled_skill_families`
in the plugin bundle's `capability_off`, which reads the same
`setup-profile.json` field the memory tool reads), a finished route is changed
one of two ways:

- The route's own pick is turned off: the dispatch target, or the candidate of
  a clarify the person named explicitly. The person asked for that work, so the
  route does not quietly hand it to another skill. It becomes a clarify on the
  router with no candidate and no shortlist, `reason_code`
  `capability_family_disabled`, and a `capability_family_off` record naming the
  family and the command that turns it back on.
- Otherwise the turned-off skills are dropped from every list the route
  offers (recommendations, the candidate handoff and its question, the route
  plan) and a clarify names its next candidate.

A home with nothing turned off never reaches this module, so the default
install and every enabled family route byte for byte as before.
"""

from __future__ import annotations

from typing import Mapping

from ..plugin_bundle.omh.capability_off import (
    CAPABILITY_OFF_REASON_CODE,
    capability_off_record,
    capability_off_sentence,
    family_label,
)
from ..skills.catalog import omh_skill_display_name, primary_harness_for_skill
from .candidate_handoff import SHORTLIST_LEXICAL, candidate_handoff_digest, shortlist_clarification
from .decision_contract import build_route_decision_contract
from .route_plan import public_workflow_identifier
from .route_question import build_route_question_for_candidate_handoff

ROUTER_SKILL = "oh-my-hermes"
CAPABILITY_OFF_KEY = "capability_family_off"
# A clarify whose every candidate was turned off asks an open question; the
# code keeps the router's instruction from naming an empty candidate.
REASON_CODE_NO_ENABLED_CANDIDATE = "no_enabled_candidate"
# Route keys that only describe a candidate set; a route whose pick is turned
# off offers no candidate, so it carries none of them.
_CANDIDATE_KEYS = (
    "candidate_handoff",
    "route_question",
    "ambiguity_kind",
    "skill_governance",
    "native_skill_recommendations",
)


def route_without_disabled_skills(
    route: dict[str, object],
    disabled: Mapping[str, str],
    *,
    message: str,
) -> dict[str, object]:
    """`route` with `disabled` (skill -> family id) taken out; unchanged when nothing in it is off."""
    if not disabled:
        return route
    disabled = _with_display_names(disabled)
    pick = _turned_off_pick(route, disabled)
    if pick:
        return _capability_off_route(route, pick, disabled[pick])
    return _without_offered(route, disabled, message=message)


def _with_display_names(disabled: Mapping[str, str]) -> dict[str, str]:
    """`disabled` keyed by every spelling a route may carry for a skill.

    A route plan names its steps by public identifier (`ulw-research`), not by
    catalog name (`research`), so a plan step of a turned-off skill matched
    nothing and kept the plan.
    """
    spellings = dict(disabled)
    for name, family_id in disabled.items():
        for alias in (omh_skill_display_name(name), public_workflow_identifier(name)):
            spellings.setdefault(alias, family_id)
    return spellings


def _turned_off_pick(route: Mapping[str, object], disabled: Mapping[str, str]) -> str:
    action = str(route.get("action") or "")
    if action == "dispatch":
        selected = str(route.get("selected_skill") or "")
        return selected if selected in disabled else ""
    # A clarify is the router asking, not the person asking: only one that
    # names the skill because the person did (`explicit`) is answered "off".
    # With a high-confidence clarify counted too, 3 to 55 negative controls
    # per family were refused instead of answered.
    candidate = str(route.get("candidate_skill") or "")
    if action == "clarify" and candidate in disabled and route.get("explicit"):
        return candidate
    return ""


def _capability_off_route(
    route: dict[str, object], skill: str, family_id: str,
) -> dict[str, object]:
    sentence = capability_off_sentence(skill, family_id)
    label = family_label(family_id)
    for key in _CANDIDATE_KEYS:
        route.pop(key, None)
    route.update(
        {
            "action": "clarify",
            "selected_skill": ROUTER_SKILL,
            "selected_harness": primary_harness_for_skill(ROUTER_SKILL),
            "candidate_skill": "",
            "candidate_harness": "",
            "reason": sentence,
            "reason_code": CAPABILITY_OFF_REASON_CODE,
            "clarification": (
                f"Tell the user the {label} capability family is turned off in this OMH home, so `{skill}` "
                f"is not offered, and that `{capability_off_record(skill, family_id)['enable_command']}` turns "
                "it back on. Do not hand the request to another workflow."
            ),
            "routing_prompt": (
                "Use the `oh-my-hermes` router and do not dispatch: the requested workflow's capability "
                f"family is turned off.\n\nRouting reason: {sentence}"
            ),
            "recommendations": [],
            "task_card": None,
            "workflow_route_plan": None,
            "learning_candidate_card": None,
            CAPABILITY_OFF_KEY: capability_off_record(skill, family_id),
        }
    )
    route["route_decision"] = build_route_decision_contract(route)
    return route


def _without_offered(
    route: dict[str, object], disabled: Mapping[str, str], *, message: str
) -> dict[str, object]:
    changed = False
    recommendations = route.get("recommendations")
    if isinstance(recommendations, list):
        kept = [item for item in recommendations if not _is_off(item, disabled)]
        if len(kept) != len(recommendations):
            route["recommendations"] = kept
            changed = True
    handoff = route.get("candidate_handoff")
    handoff_candidates: list[dict[str, object]] | None = None
    if isinstance(handoff, dict) and isinstance(handoff.get("candidates"), list):
        rows = [row for row in handoff["candidates"] if isinstance(row, dict)]
        handoff_candidates = [row for row in rows if not _is_off(row, disabled)]
        if len(handoff_candidates) != len(handoff["candidates"]):
            reasons = tuple(str(reason) for reason in handoff.get("reasons", []) if isinstance(reason, str))
            handoff = {
                **handoff,
                "candidates": handoff_candidates,
                "candidate_count": len(handoff_candidates),
                "selection_mode": "candidate_selection" if handoff_candidates else "open_clarification",
                "digest": candidate_handoff_digest(handoff_candidates, reasons),
            }
            route["candidate_handoff"] = handoff
            if "route_question" in route:
                route["route_question"] = build_route_question_for_candidate_handoff(handoff, message=message)
            changed = True
    plan = route.get("workflow_route_plan")
    if isinstance(plan, dict) and any(_is_off(step, disabled) for step in plan.get("steps", []) or []):
        route["workflow_route_plan"] = None
        changed = True
    candidate = str(route.get("candidate_skill") or "")
    if candidate in disabled:
        offered = handoff_candidates if handoff_candidates is not None else route.get("recommendations", [])
        replacement = next(
            (str(row.get("skill") or "") for row in offered or [] if isinstance(row, dict) and row.get("skill")),
            "",
        )
        route["candidate_skill"] = replacement
        route["candidate_harness"] = primary_harness_for_skill(replacement) if replacement else ""
        if not replacement and route.get("action") == "clarify":
            route["reason_code"] = REASON_CODE_NO_ENABLED_CANDIDATE
        changed = True
    if _names_any(str(route.get("clarification") or ""), disabled):
        route["clarification"] = _clarification(route, handoff_candidates)
        changed = True
    if _names_any(str(route.get("routing_prompt") or ""), disabled):
        route["routing_prompt"] = _routing_prompt(route)
        changed = True
    if changed:
        route["route_decision"] = build_route_decision_contract(route)
    return route


def _is_off(row: object, disabled: Mapping[str, str]) -> bool:
    return isinstance(row, dict) and str(row.get("skill") or "") in disabled


def _names_any(text: str, disabled: Mapping[str, str]) -> bool:
    return bool(text) and any(f"`{skill}`" in text for skill in disabled)


def _clarification(route: Mapping[str, object], handoff_candidates: list[dict[str, object]] | None) -> str:
    handoff = route.get("candidate_handoff")
    if (
        handoff_candidates
        and isinstance(handoff, dict)
        and handoff.get("shortlist_source") == SHORTLIST_LEXICAL
    ):
        return shortlist_clarification(handoff_candidates)
    candidate = str(route.get("candidate_skill") or "")
    if candidate:
        return f"Ask whether to use `{candidate}` for the requested outcome."
    return "Ask what outcome the user wants, or present the workflow picker without naming a skill."


def _routing_prompt(route: Mapping[str, object]) -> str:
    reason = str(route.get("reason") or "")
    selected = str(route.get("selected_skill") or "")
    if route.get("action") == "dispatch" and selected:
        return f"Use the `{selected}` workflow for this chat message.\n\nRouting reason: {reason}"
    candidate = str(route.get("candidate_skill") or "")
    if candidate:
        return f"Use the `oh-my-hermes` router before dispatching to `{candidate}`.\n\nRouting reason: {reason}"
    return (
        "Use the `oh-my-hermes` router and ask one open clarification question without naming a skill.\n\n"
        f"Routing reason: {reason}"
    )


__all__ = ["CAPABILITY_OFF_KEY", "REASON_CODE_NO_ENABLED_CANDIDATE", "ROUTER_SKILL", "route_without_disabled_skills"]
