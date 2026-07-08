from __future__ import annotations

import argparse

from omh.installer import OmhError
from omh.web_visual_qa import (
    build_web_visual_qa_message_card,
    build_web_visual_qa_package,
    read_web_visual_qa_package,
    save_web_visual_qa_package,
    validate_web_visual_qa_message_card,
    validate_web_visual_qa_package,
    write_web_visual_qa_package,
)
from omh.workflows.web_visual_qa_contracts import JsonObject, now, object_list, text

from .common import _paths, _print_json, _wants_json


def cmd_web_qa_package(args: argparse.Namespace) -> int:
    try:
        package = build_web_visual_qa_package(
            package_id=args.package_id,
            target=args.target,
            source=args.source,
            risk_level=args.risk_level,
            estimated_cost_tier=args.estimated_cost_tier,
            criteria=[_parse_criterion(value) for value in args.criterion],
            captures=[_parse_capture(value) for value in args.capture or []],
            criteria_results=[_parse_criteria_result(value) for value in args.criteria_result or []],
            multimodal_reviews=[_parse_multimodal_review(value) for value in args.multimodal_review or []],
            verdict=args.verdict,
        )
        written = write_web_visual_qa_package(_paths(args), package)
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_or_summarize(args, written)
    return 0


def cmd_web_qa_observe_capture(args: argparse.Namespace) -> int:
    try:
        current = read_web_visual_qa_package(_paths(args), args.package_id)
        observed_at = now()
        updated = _rebuild(
            current,
            captures=object_list(current.get("captures")) + [
                {
                    "capture_id": args.capture_id,
                    "role": args.role,
                    "path_or_uri": args.path,
                    "mime_type": args.mime_type,
                    "viewport": args.viewport,
                    "captured_at": observed_at,
                    "evidence_summary": args.summary,
                    "observer": args.observer,
                    "redaction_status": args.redaction_status,
                }
            ],
            updated_at=observed_at,
        )
        saved = save_web_visual_qa_package(_paths(args), updated)
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_or_summarize(args, saved)
    return 0


def cmd_web_qa_record_verdict(args: argparse.Namespace) -> int:
    try:
        current = read_web_visual_qa_package(_paths(args), args.package_id)
        updated = _rebuild(
            current,
            criteria_results=object_list(current.get("criteria_results"))
            + [_parse_criteria_result(value) for value in args.criteria_result],
            multimodal_reviews=object_list(current.get("multimodal_reviews"))
            + [_parse_multimodal_review(value) for value in args.multimodal_review or []],
            verdict=args.verdict,
        )
        saved = save_web_visual_qa_package(_paths(args), updated)
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_or_summarize(args, saved)
    return 0


def cmd_web_qa_show(args: argparse.Namespace) -> int:
    try:
        current = read_web_visual_qa_package(_paths(args), args.package_id)
        package_errors = validate_web_visual_qa_package(current)
        if package_errors:
            raise ValueError("; ".join(package_errors))
        card = build_web_visual_qa_message_card(current)
        errors = validate_web_visual_qa_message_card(card)
        if errors:
            raise ValueError("; ".join(errors))
    except (OSError, ValueError) as exc:
        raise OmhError(str(exc)) from exc
    _print_card_or_summarize(args, card)
    return 0


def _rebuild(
    current: JsonObject,
    *,
    captures: list[JsonObject] | None = None,
    criteria_results: list[JsonObject] | None = None,
    multimodal_reviews: list[JsonObject] | None = None,
    verdict: str | None = None,
    updated_at: str = "",
) -> JsonObject:
    return build_web_visual_qa_package(
        package_id=text(current.get("package_id")),
        target=text(current.get("target")),
        source=text(current.get("source")) or "generic",
        risk_level=text(current.get("risk_level")) or "unknown",
        estimated_cost_tier=text(current.get("estimated_cost_tier")) or "none",
        criteria=object_list(current.get("criteria")),
        captures=captures if captures is not None else object_list(current.get("captures")),
        criteria_results=criteria_results if criteria_results is not None else object_list(current.get("criteria_results")),
        multimodal_reviews=multimodal_reviews if multimodal_reviews is not None else object_list(current.get("multimodal_reviews")),
        interaction_traces=object_list(current.get("interaction_traces")),
        verdict=verdict or text(current.get("verdict")) or "not_observed",
        created_at=text(current.get("created_at")),
        updated_at=updated_at or now(),
    )


def _parse_criterion(value: str) -> JsonObject:
    criterion_id, label, pass_rule, severity = _split(value, 4, "criterion")
    return {"criterion_id": criterion_id, "label": label, "pass_rule": pass_rule, "severity": severity}


def _parse_capture(value: str) -> JsonObject:
    capture_id, role, path, mime_type, viewport, summary = _split(value, 6, "capture")
    return {
        "capture_id": capture_id,
        "role": role,
        "path_or_uri": path,
        "mime_type": mime_type,
        "viewport": viewport,
        "evidence_summary": summary,
    }


def _parse_criteria_result(value: str) -> JsonObject:
    criterion_id, status, refs, checked_by, summary, blocking = _split(value, 6, "criteria-result")
    return {
        "criterion_id": criterion_id,
        "status": status,
        "evidence_refs": [item.strip() for item in refs.split(",") if item.strip()],
        "checked_by": checked_by,
        "summary": summary,
        "blocking": blocking != "nonblocking",
    }


def _parse_multimodal_review(value: str) -> JsonObject:
    review_id, status, reviewer, cost_tier, confidence, refs, summary = _split(value, 7, "multimodal-review")
    return {
        "review_id": review_id,
        "status": status,
        "reviewer": reviewer,
        "cost_tier": cost_tier,
        "confidence": confidence,
        "evidence_refs": [item.strip() for item in refs.split(",") if item.strip()],
        "summary": summary,
    }


def _split(value: str, count: int, label: str) -> list[str]:
    parts = [part.strip() for part in value.split(":", count - 1)]
    if len(parts) != count or any(not part for part in parts):
        raise ValueError(f"--{label} must contain exactly {count} colon-separated fields")
    return parts


def _print_or_summarize(args: argparse.Namespace, package: JsonObject) -> None:
    if _wants_json(args):
        _print_json(package)
        return
    print("Web visual QA package recorded.")
    print(f"Package: {package['package_id']}")
    print(f"Status: {package['status']}")
    print(f"Verdict: {package['verdict']}")
    print(f"Routing: {text(package.get('routing'))}")
    print("Not evidence yet: browser capture by OMH, multimodal model call by OMH, platform delivery.")


def _print_card_or_summarize(args: argparse.Namespace, card: JsonObject) -> None:
    if _wants_json(args):
        _print_json(card)
        return
    route = card["route"] if isinstance(card.get("route"), dict) else {}
    attachment_summary = card["attachment_summary"] if isinstance(card.get("attachment_summary"), dict) else {}
    print("Web visual QA message card")
    print(f"Package: {card['package_id']}")
    print(f"Target: {card['target']}")
    print(f"Verdict: {card['verdict']}")
    print(f"Route: {text(route.get('label'))}")
    print(
        "Attachments: "
        f"{attachment_summary.get('eligible_count', 0)} eligible, "
        f"{attachment_summary.get('blocked_count', 0)} blocked; "
        f"delivery {'observed' if attachment_summary.get('delivery_observed') is True else 'not observed'}"
    )
    criteria = [item for item in object_list(card.get("criteria"))]
    if criteria:
        print("Criteria:")
        for criterion in criteria:
            label = text(criterion.get("label")) or text(criterion.get("criterion_id")) or "criterion"
            print(f"- {label}: {text(criterion.get('status'))} - {text(criterion.get('summary'))}")
    boundary = text(card.get("claim_boundary"))
    if boundary:
        print("Boundary:")
        print(f"  {boundary}")
    print("Use --json for the full message-card projection.")


def _add_web_qa_commands(sub) -> None:
    web_qa = sub.add_parser(
        "web-qa",
        help="Prepare and record screenshot-backed web visual QA evidence packages.",
    )
    web_qa_sub = web_qa.add_subparsers(dest="web_qa_command", required=True)

    package = web_qa_sub.add_parser("package", help="Create a web_visual_qa_package/v1 from supplied metadata.")
    package.add_argument("--package-id", default="")
    package.add_argument("--target", required=True)
    package.add_argument("--source", choices=("discord", "slack", "hermes", "generic"), default="generic")
    package.add_argument("--risk-level", choices=("low", "medium", "high", "critical", "unknown"), default="unknown")
    package.add_argument("--estimated-cost-tier", choices=("none", "low", "medium", "high", "unknown"), default="none")
    package.add_argument("--criterion", action="append", required=True, metavar="ID:LABEL:PASS_RULE:SEVERITY")
    package.add_argument("--capture", action="append", metavar="ID:ROLE:PATH:MIME:VIEWPORT:SUMMARY")
    package.add_argument("--criteria-result", action="append", metavar="CRITERION:STATUS:REFS:CHECKED_BY:SUMMARY:BLOCKING")
    package.add_argument("--multimodal-review", action="append", metavar="ID:STATUS:REVIEWER:COST:CONFIDENCE:REFS:SUMMARY")
    package.add_argument("--verdict", choices=("pass", "hold", "fail", "not_observed"), default="not_observed")
    package.add_argument("--json", action="store_true")
    package.set_defaults(func=cmd_web_qa_package)

    observe = web_qa_sub.add_parser("observe-capture", help="Add supplied screenshot/capture metadata to a package.")
    observe.add_argument("--package-id", required=True)
    observe.add_argument("--capture-id", required=True)
    observe.add_argument("--role", default="current")
    observe.add_argument("--path", required=True)
    observe.add_argument("--mime-type", default="")
    observe.add_argument("--viewport", default="unspecified")
    observe.add_argument("--summary", required=True)
    observe.add_argument("--observer", default="wrapper_or_user")
    observe.add_argument("--redaction-status", default="unknown")
    observe.add_argument("--json", action="store_true")
    observe.set_defaults(func=cmd_web_qa_observe_capture)

    verdict = web_qa_sub.add_parser("record-verdict", help="Record criteria results and a web visual QA verdict.")
    verdict.add_argument("--package-id", required=True)
    verdict.add_argument("--criteria-result", action="append", required=True, metavar="CRITERION:STATUS:REFS:CHECKED_BY:SUMMARY:BLOCKING")
    verdict.add_argument("--multimodal-review", action="append", metavar="ID:STATUS:REVIEWER:COST:CONFIDENCE:REFS:SUMMARY")
    verdict.add_argument("--verdict", choices=("pass", "hold", "fail", "not_observed"), required=True)
    verdict.add_argument("--json", action="store_true")
    verdict.set_defaults(func=cmd_web_qa_record_verdict)

    show = web_qa_sub.add_parser("show", help="Show a message-card projection for a recorded package.")
    show.add_argument("--package-id", required=True)
    show.add_argument("--json", action="store_true")
    show.set_defaults(func=cmd_web_qa_show)


__all__ = [
    "_add_web_qa_commands",
    "cmd_web_qa_observe_capture",
    "cmd_web_qa_package",
    "cmd_web_qa_record_verdict",
    "cmd_web_qa_show",
]
