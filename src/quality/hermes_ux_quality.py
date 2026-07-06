from __future__ import annotations

from typing import Mapping, Sequence

from ..ingress import CHAT_SOURCES
from .chat_card_coverage import build_chat_card_coverage_demo
from .common_request_coverage import build_common_request_coverage_demo, common_request_coverage_errors
from .context_brief_coverage import build_context_brief_coverage_demo
from .grounded_score import build_grounded_score_demo
from .localized_chat_copy import build_localized_chat_copy_demo, localized_chat_copy_errors
from .route_hint_alignment import build_route_hint_alignment_demo
from .router_fast_path import build_router_fast_path_demo, router_fast_path_errors
from .routing_precision import build_routing_precision_demo, routing_precision_errors


HERMES_UX_QUALITY_SCHEMA_VERSION = "hermes_ux_quality/v1"


def build_hermes_ux_quality_demo(
    *,
    source: str = "discord",
    grounded_score: Mapping[str, object] | None = None,
    chat_card_coverage: Mapping[str, object] | None = None,
    route_hint_alignment: Mapping[str, object] | None = None,
    context_brief_coverage: Mapping[str, object] | None = None,
    routing_precision: Mapping[str, object] | None = None,
    localized_chat_copy: Mapping[str, object] | None = None,
    router_fast_path: Mapping[str, object] | None = None,
    common_request_coverage: Mapping[str, object] | None = None,
) -> dict[str, object]:
    if source not in CHAT_SOURCES:
        raise ValueError(f"unsupported demo source: {source}")
    grounded = dict(grounded_score) if grounded_score is not None else build_grounded_score_demo(source=source)
    chat_cards = (
        dict(chat_card_coverage)
        if chat_card_coverage is not None
        else build_chat_card_coverage_demo(source=source)
    )
    route_hints = (
        dict(route_hint_alignment)
        if route_hint_alignment is not None
        else build_route_hint_alignment_demo(
            source=source,
            grounded_score=grounded,
            chat_card_coverage=chat_cards,
        )
    )
    context_briefs = (
        dict(context_brief_coverage)
        if context_brief_coverage is not None
        else build_context_brief_coverage_demo(source=source)
    )
    precision = (
        dict(routing_precision)
        if routing_precision is not None
        else build_routing_precision_demo(source=source)
    )
    localized_copy = (
        dict(localized_chat_copy)
        if localized_chat_copy is not None
        else build_localized_chat_copy_demo(source=source)
    )
    fast_paths = (
        dict(router_fast_path)
        if router_fast_path is not None
        else build_router_fast_path_demo(source=source)
    )
    common_requests = (
        dict(common_request_coverage)
        if common_request_coverage is not None
        else build_common_request_coverage_demo(source=source)
    )

    gates = [
        _gate(
            gate_id="grounded_score",
            title="Natural-language routing",
            status="passed" if _grounded_ready(grounded) else "failed",
            summary=_grounded_summary(grounded),
            user_value="Representative operator prompts land on the expected OMH workflow with a 10/10 local score.",
            command="omh demo grounded-score --json",
            errors=_grounded_errors(grounded),
            claim_boundary=str(grounded.get("claim_boundary", "")),
        ),
        _gate(
            gate_id="chat_card_coverage",
            title="Dedicated Hermes cards",
            status="passed" if _chat_cards_ready(chat_cards) else "failed",
            summary=_chat_card_summary(chat_cards),
            user_value="Hermes can show a workflow-specific card instead of a generic acknowledgement.",
            command="omh demo chat-card-coverage --json",
            errors=_chat_card_errors(chat_cards),
            claim_boundary=str(chat_cards.get("claim_boundary", "")),
        ),
        _gate(
            gate_id="route_hint_alignment",
            title="Plugin awareness hint alignment",
            status="passed" if _route_hints_ready(route_hints) else "failed",
            summary=_route_hint_summary(route_hints),
            user_value="Wrapper/plugin route hints agree with the chat router before generic tools take over.",
            command="omh demo route-hint-alignment --json",
            errors=_route_hint_errors(route_hints),
            claim_boundary=str(route_hints.get("claim_boundary", "")),
        ),
        _gate(
            gate_id="context_brief_coverage",
            title="First-turn OMH mental model",
            status="passed" if _context_briefs_ready(context_briefs) else "failed",
            summary=_context_brief_summary(context_briefs),
            user_value="Hermes receives bounded OMH context, workflow hints, and catalog picker hints without raw prompt leakage.",
            command="omh demo context-brief-coverage --json",
            errors=_context_brief_errors(context_briefs),
            claim_boundary=str(context_briefs.get("claim_boundary", "")),
        ),
        _gate(
            gate_id="routing_precision",
            title="Over-intervention guard",
            status="passed" if _routing_precision_ready(precision) else "failed",
            summary=_routing_precision_summary(precision),
            user_value="Ordinary questions stay as direct answers or file lookups instead of opening OMH workflow cards.",
            command="omh demo routing-precision --json",
            errors=routing_precision_errors(precision),
            claim_boundary=str(precision.get("claim_boundary", "")),
        ),
        _gate(
            gate_id="localized_chat_copy",
            title="Localized chat-card framing",
            status="passed" if _localized_copy_ready(localized_copy) else "failed",
            summary=_localized_copy_summary(localized_copy),
            user_value="Common non-English operator prompts get local card framing without translation APIs or route drift.",
            command="omh demo localized-chat-copy --json",
            errors=localized_chat_copy_errors(localized_copy),
            claim_boundary=str(localized_copy.get("claim_boundary", "")),
        ),
        _gate(
            gate_id="router_fast_path",
            title="Perceived chat latency guard",
            status="passed" if _router_fast_path_ready(fast_paths) else "failed",
            summary=_router_fast_path_summary(fast_paths),
            user_value="High-frequency chat turns stay on explicit fast-path routes instead of falling through to full workflow scoring.",
            command="omh demo router-fast-path --json",
            errors=router_fast_path_errors(fast_paths),
            claim_boundary=str(fast_paths.get("claim_boundary", "")),
        ),
        _gate(
            gate_id="common_request_coverage",
            title="Ordinary request coverage breadth",
            status="passed" if _common_requests_ready(common_requests) else "failed",
            summary=_common_request_summary(common_requests),
            user_value="OMH covers a broad curated set of ordinary Hermes-agent asks instead of only a few demo prompts.",
            command="omh demo common-request-coverage --json",
            errors=common_request_coverage_errors(common_requests),
            claim_boundary=str(common_requests.get("claim_boundary", "")),
        ),
    ]
    passing_count = sum(1 for gate in gates if gate["status"] == "passed")
    total = len(gates)
    status = "passed" if passing_count == total else "needs_attention"
    grounded_summary = _nested(grounded, "summary")
    chat_summary = _nested(chat_cards, "summary")
    route_summary = _nested(route_hints, "summary")
    context_summary = _nested(context_briefs, "summary")
    precision_summary = _nested(precision, "summary")
    localized_summary = _nested(localized_copy, "summary")
    fast_path_summary = _nested(fast_paths, "summary")
    common_request_summary = _nested(common_requests, "summary")
    return {
        "schema_version": HERMES_UX_QUALITY_SCHEMA_VERSION,
        "source": source,
        "status": status,
        "score": round((passing_count / max(1, total)) * 100),
        "summary": {
            "gate_count": total,
            "passing_gate_count": passing_count,
            "grounded_score_scenarios": grounded_summary.get("scenario_count", 0),
            "grounded_score_average": grounded_summary.get("average_score", 0),
            "chat_card_cases": chat_summary.get("case_count", 0),
            "chat_card_generic_ack_count": chat_summary.get("generic_ack_count", 0),
            "route_hint_cases": route_summary.get("case_count", 0),
            "route_hint_aligned_count": route_summary.get("aligned_count", 0),
            "route_hint_missing_count": route_summary.get("missing_hint_count", 0),
            "route_hint_mismatch_count": route_summary.get("mismatch_count", 0),
            "context_brief_cases": context_summary.get("case_count", 0),
            "context_brief_passing_count": context_summary.get("passing_count", 0),
            "context_brief_route_hint_count": context_summary.get("route_hint_count", 0),
            "context_brief_catalog_question_count": context_summary.get("catalog_question_count", 0),
            "routing_precision_cases": precision_summary.get("case_count", 0),
            "routing_precision_passing_count": precision_summary.get("passing_count", 0),
            "routing_precision_overroute_count": precision_summary.get("overroute_count", 0),
            "routing_precision_catalog_picker_count": precision_summary.get("catalog_picker_count", 0),
            "routing_precision_generic_ack_count": precision_summary.get("generic_ack_count", 0),
            "routing_precision_intervention_cases": precision_summary.get("intervention_case_count", 0),
            "routing_precision_intervention_passing_count": precision_summary.get("intervention_passing_count", 0),
            "routing_precision_missed_intervention_count": precision_summary.get("missed_intervention_count", 0),
            "localized_chat_copy_cases": localized_summary.get("case_count", 0),
            "localized_chat_copy_passing_count": localized_summary.get("passing_count", 0),
            "localized_chat_copy_locale_count": localized_summary.get("locale_count", 0),
            "router_fast_path_cases": fast_path_summary.get("case_count", 0),
            "router_fast_path_passing_count": fast_path_summary.get("passing_count", 0),
            "router_fast_path_missing_marker_count": fast_path_summary.get("missing_marker_count", 0),
            "common_request_cases": common_request_summary.get("case_count", 0),
            "common_request_passing_count": common_request_summary.get("passing_count", 0),
            "common_request_coverage_percent": common_request_summary.get("coverage_percent", 0),
            "common_request_target_percent": common_requests.get("target_percent", 0),
            "common_request_generic_ack_count": common_request_summary.get("generic_ack_count", 0),
        },
        "user_story": [
            "Natural chat requests route to an OMH workflow instead of a vague generic answer.",
            "Hermes can render workflow-specific next actions and evidence boundaries.",
            "Plugin/context awareness agrees with the router before generic tools are used.",
            "Catalog questions open an OMH picker without asking the user to approve shell commands.",
            "Plain help and file lookup questions stay out of OMH workflow routing when OMH is not needed.",
            "Common non-English operator prompts get local card framing without external translation.",
            "Frequent picker, status, direct-answer, file lookup, and workflow requests stay on deterministic fast paths.",
            "Real OMH-shaped requests still route to the expected workflow, picker, or context brief.",
            "A curated ordinary-request corpus stays above the 95% breadth target while preserving direct answers.",
        ],
        "gates": gates,
        "claim_boundary": (
            "Hermes UX quality proves deterministic local routing, card, hint, context, precision, "
            "localized-copy, fast-path, and common-request breadth contracts only. "
            "It does not prove live Hermes chat rendering, platform delivery, plugin load, generic tool invocation, "
            "source retrieval, image generation, executor dispatch, implementation, verification, review, CI, merge, "
            "or delivery."
        ),
    }


def format_hermes_ux_quality_summary(payload: Mapping[str, object]) -> str:
    summary = _nested(payload, "summary")
    gates = _mapping_rows(payload.get("gates"))
    lines = [
        "OMH Hermes UX quality",
        f"Source: {payload.get('source', 'unknown')}",
        f"Status: {payload.get('status', 'unknown')} ({payload.get('score', 0)}/100)",
        (
            f"Gates: {summary.get('passing_gate_count', 0)}/{summary.get('gate_count', len(gates))}; "
            f"routing avg {summary.get('grounded_score_average', 0)}; "
            f"generic ack {summary.get('chat_card_generic_ack_count', 0)}; "
            f"route mismatches {summary.get('route_hint_mismatch_count', 0)}; "
            f"context {summary.get('context_brief_passing_count', 0)}/{summary.get('context_brief_cases', 0)}; "
            f"precision overroutes {summary.get('routing_precision_overroute_count', 0)}; "
            f"missed interventions {summary.get('routing_precision_missed_intervention_count', 0)}; "
            f"localized {summary.get('localized_chat_copy_passing_count', 0)}/{summary.get('localized_chat_copy_cases', 0)}; "
            f"fast paths {summary.get('router_fast_path_passing_count', 0)}/{summary.get('router_fast_path_cases', 0)}; "
            f"common requests {summary.get('common_request_passing_count', 0)}/{summary.get('common_request_cases', 0)} "
            f"({summary.get('common_request_coverage_percent', 0)}%)"
        ),
        "",
        "What users feel:",
    ]
    for story in _string_items(payload.get("user_story")):
        lines.append(f"- {story}")
    lines.extend(["", "Quality gates:"])
    for gate in gates:
        lines.append(f"- {gate.get('id', 'unknown')}: {gate.get('status', 'unknown')}; {gate.get('summary', '')}")
        errors = _string_items(gate.get("errors"))
        if errors:
            lines.append(f"  errors: {', '.join(errors)}")
    lines.extend(
        [
            "",
            f"Boundary: {payload.get('claim_boundary', '')}",
            "Use --json for the full machine-readable payload.",
        ]
    )
    return "\n".join(lines)


def hermes_ux_quality_errors(payload: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != HERMES_UX_QUALITY_SCHEMA_VERSION:
        errors.append("unexpected_schema")
    if payload.get("status") != "passed":
        errors.append(f"status_{payload.get('status', 'unknown')}")
    for gate in _mapping_rows(payload.get("gates")):
        if gate.get("status") == "passed":
            continue
        gate_id = str(gate.get("id") or "unknown")
        gate_errors = ", ".join(_string_items(gate.get("errors"))) or str(gate.get("summary") or "failed")
        errors.append(f"{gate_id}: {gate_errors}")
    return errors


def _gate(
    *,
    gate_id: str,
    title: str,
    status: str,
    summary: str,
    user_value: str,
    command: str,
    errors: Sequence[str],
    claim_boundary: str,
) -> dict[str, object]:
    return {
        "id": gate_id,
        "title": title,
        "status": status,
        "summary": summary,
        "user_value": user_value,
        "command": command,
        "errors": list(errors),
        "claim_boundary": claim_boundary,
    }


def _grounded_ready(payload: Mapping[str, object]) -> bool:
    summary = _nested(payload, "summary")
    return bool(summary.get("all_10")) and int(summary.get("scenario_count", 0) or 0) > 0


def _chat_cards_ready(payload: Mapping[str, object]) -> bool:
    summary = _nested(payload, "summary")
    return bool(summary.get("all_passing")) and int(summary.get("generic_ack_count", 0) or 0) == 0


def _route_hints_ready(payload: Mapping[str, object]) -> bool:
    summary = _nested(payload, "summary")
    return (
        bool(summary.get("all_aligned"))
        and int(summary.get("missing_hint_count", 0) or 0) == 0
        and int(summary.get("mismatch_count", 0) or 0) == 0
    )


def _context_briefs_ready(payload: Mapping[str, object]) -> bool:
    summary = _nested(payload, "summary")
    return (
        bool(summary.get("all_passing"))
        and int(summary.get("route_hint_count", 0) or 0) > 0
        and int(summary.get("catalog_question_count", 0) or 0) > 0
    )


def _routing_precision_ready(payload: Mapping[str, object]) -> bool:
    return not routing_precision_errors(payload)


def _localized_copy_ready(payload: Mapping[str, object]) -> bool:
    return not localized_chat_copy_errors(payload)


def _router_fast_path_ready(payload: Mapping[str, object]) -> bool:
    return not router_fast_path_errors(payload)


def _common_requests_ready(payload: Mapping[str, object]) -> bool:
    return not common_request_coverage_errors(payload)


def _grounded_summary(payload: Mapping[str, object]) -> str:
    summary = _nested(payload, "summary")
    return (
        f"{summary.get('scenario_count', 0)}/{summary.get('scenario_count', 0)} scenarios at 10/10; "
        f"min {summary.get('minimum_score', 0)}, avg {summary.get('average_score', 0)}, max {summary.get('maximum_score', 0)}"
    )


def _chat_card_summary(payload: Mapping[str, object]) -> str:
    summary = _nested(payload, "summary")
    return (
        f"{summary.get('passing_count', 0)}/{summary.get('case_count', 0)} dedicated workflow cards; "
        f"generic ack {summary.get('generic_ack_count', 0)}"
    )


def _route_hint_summary(payload: Mapping[str, object]) -> str:
    summary = _nested(payload, "summary")
    return (
        f"{summary.get('aligned_count', 0)}/{summary.get('case_count', 0)} route hints aligned; "
        f"missing {summary.get('missing_hint_count', 0)}; mismatches {summary.get('mismatch_count', 0)}"
    )


def _context_brief_summary(payload: Mapping[str, object]) -> str:
    summary = _nested(payload, "summary")
    return (
        f"{summary.get('passing_count', 0)}/{summary.get('case_count', 0)} context brief cases passing; "
        f"route hints {summary.get('route_hint_count', 0)}; "
        f"catalog picker hints {summary.get('catalog_question_count', 0)}"
    )


def _routing_precision_summary(payload: Mapping[str, object]) -> str:
    summary = _nested(payload, "summary")
    return (
        f"{summary.get('passing_count', 0)}/{summary.get('case_count', 0)} negative-control cases; "
        f"{summary.get('intervention_passing_count', 0)}/{summary.get('intervention_case_count', 0)} interventions; "
        f"overroutes {summary.get('overroute_count', 0)}; "
        f"catalog pickers {summary.get('catalog_picker_count', 0)}; "
        f"generic ack {summary.get('generic_ack_count', 0)}; "
        f"missed interventions {summary.get('missed_intervention_count', 0)}"
    )


def _localized_copy_summary(payload: Mapping[str, object]) -> str:
    summary = _nested(payload, "summary")
    return (
        f"{summary.get('passing_count', 0)}/{summary.get('case_count', 0)} localized card cases; "
        f"locales {summary.get('locale_count', 0)}"
    )


def _router_fast_path_summary(payload: Mapping[str, object]) -> str:
    summary = _nested(payload, "summary")
    return (
        f"{summary.get('passing_count', 0)}/{summary.get('case_count', 0)} fast-path cases; "
        f"missing markers {summary.get('missing_marker_count', 0)}; "
        f"route mismatches {summary.get('route_mismatch_count', 0)}"
    )


def _common_request_summary(payload: Mapping[str, object]) -> str:
    summary = _nested(payload, "summary")
    return (
        f"{summary.get('passing_count', 0)}/{summary.get('case_count', 0)} common request cases; "
        f"coverage {summary.get('coverage_percent', 0)}%; target {payload.get('target_percent', 0)}%; "
        f"generic ack {summary.get('generic_ack_count', 0)}"
    )


def _grounded_errors(payload: Mapping[str, object]) -> list[str]:
    if _grounded_ready(payload):
        return []
    return [f"{row.get('id', 'unknown')}: score {row.get('score', 'unknown')}" for row in _mapping_rows(payload.get("scenarios")) if int(row.get("score", 0) or 0) < 10]


def _chat_card_errors(payload: Mapping[str, object]) -> list[str]:
    if _chat_cards_ready(payload):
        return []
    return [f"{row.get('id', 'unknown')}: {', '.join(_string_items(row.get('issues'))) or 'failed'}" for row in _mapping_rows(payload.get("cases")) if not row.get("passed")]


def _route_hint_errors(payload: Mapping[str, object]) -> list[str]:
    if _route_hints_ready(payload):
        return []
    return [f"{row.get('id', 'unknown')}: {', '.join(_string_items(row.get('issues'))) or 'failed'}" for row in _mapping_rows(payload.get("cases")) if not row.get("aligned")]


def _context_brief_errors(payload: Mapping[str, object]) -> list[str]:
    if _context_briefs_ready(payload):
        return []
    return [f"{row.get('id', 'unknown')}: {', '.join(_string_items(row.get('issues'))) or 'failed'}" for row in _mapping_rows(payload.get("cases")) if not row.get("passed")]


def _nested(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    return value if isinstance(value, Mapping) else {}


def _mapping_rows(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _string_items(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value if str(item)]
