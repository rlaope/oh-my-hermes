from __future__ import annotations

from dataclasses import dataclass
import hashlib

from ..ingress import CHAT_SOURCES
from ..plugin_bundle.omh.awareness import awareness_route_hint
from ..wrapper.contract import build_chat_interaction_payload
from .chat_card_coverage import CHAT_CARD_COVERAGE_CASES
from .grounded_score import GROUNDED_SCENARIOS


ROUTE_HINT_ALIGNMENT_SCHEMA_VERSION = "route_hint_alignment/v1"


@dataclass(frozen=True)
class RouteHintAlignmentCase:
    corpus: str
    id: str
    title: str
    message: str
    expected_workflow: str


def route_hint_alignment_cases() -> tuple[RouteHintAlignmentCase, ...]:
    return tuple(
        [
            RouteHintAlignmentCase(
                "grounded_score",
                scenario.id,
                scenario.title,
                scenario.message,
                scenario.expected_skill,
            )
            for scenario in GROUNDED_SCENARIOS
        ]
        + [
            RouteHintAlignmentCase(
                "chat_card_coverage",
                case.id,
                case.title,
                case.message,
                case.expected_skill,
            )
            for case in CHAT_CARD_COVERAGE_CASES
        ]
    )


def build_route_hint_alignment_demo(*, source: str = "discord") -> dict[str, object]:
    if source not in CHAT_SOURCES:
        raise ValueError(f"unsupported demo source: {source}")
    rows = [_evaluate_alignment_case(case, source=source) for case in route_hint_alignment_cases()]
    aligned_count = sum(1 for row in rows if bool(row["aligned"]))
    hinted_count = sum(1 for row in rows if _nested(row, "observed").get("hint_status") == "hinted")
    return {
        "schema_version": ROUTE_HINT_ALIGNMENT_SCHEMA_VERSION,
        "source": source,
        "summary": {
            "case_count": len(rows),
            "hinted_count": hinted_count,
            "aligned_count": aligned_count,
            "missing_hint_count": len(rows) - hinted_count,
            "mismatch_count": len(rows) - aligned_count,
            "all_aligned": bool(rows) and aligned_count == len(rows),
        },
        "check_basis": [
            "The chat router selects the expected workflow for each representative operator message.",
            "The plugin awareness route hint returns a primary workflow instead of no_hint.",
            "The primary hint workflow matches the chat router and the expected public workflow.",
            "The hint carries a workflow context card and advisory-only claim boundary.",
            "This gate checks deterministic router/hint agreement only; it is not live Hermes rendering or execution evidence.",
        ],
        "cases": rows,
        "claim_boundary": (
            "Route hint alignment proves deterministic local agreement between chat routing and plugin awareness hints. "
            "It does not prove live Hermes chat rendering, platform delivery, executor execution, review, CI, merge, "
            "or plugin-load evidence."
        ),
    }


def format_route_hint_alignment_summary(payload: dict[str, object]) -> str:
    summary = _nested(payload, "summary")
    rows = _dict_rows(payload.get("cases", []))
    total = int(summary.get("case_count", len(rows)) or 0)
    aligned = int(summary.get("aligned_count", 0) or 0)
    hinted = int(summary.get("hinted_count", 0) or 0)
    missing = int(summary.get("missing_hint_count", 0) or 0)
    mismatches = int(summary.get("mismatch_count", 0) or 0)
    all_aligned = bool(summary.get("all_aligned", False))
    lines = [
        "OMH route hint alignment",
        f"Source: {payload.get('source', 'unknown')}",
        f"Result: {aligned}/{total} route hints aligned" + (" (all passing)" if all_aligned else ""),
        f"Hints present: {hinted}/{total}; missing hints: {missing}; mismatches: {mismatches}",
        "",
        "What this proves:",
    ]
    for basis in payload.get("check_basis", []):
        lines.append(f"- {basis}")
    lines.extend(["", "Alignment rollup:"])
    for row in rows:
        observed = _nested(row, "observed")
        status = "ok" if row.get("aligned") else "needs attention"
        lines.append(
            f"- {row.get('title', 'Untitled route')}: {status}; "
            f"route={observed.get('route_workflow', 'unknown')} "
            f"hint={observed.get('hint_workflow', 'unknown')} "
            f"hint_action={observed.get('hint_next_action', 'unknown')}"
        )
    failed = [row for row in rows if not row.get("aligned")]
    if failed:
        lines.extend(["", "Failures:"])
        for row in failed:
            lines.append(f"- {row.get('corpus', 'unknown')}:{row.get('id', 'unknown')}: {', '.join(row.get('issues', [])) or 'unknown issue'}")
    lines.extend(
        [
            "",
            f"Boundary: {payload.get('claim_boundary', '')}",
            "Use --json for the full machine-readable payload.",
        ]
    )
    return "\n".join(lines)


def _evaluate_alignment_case(case: RouteHintAlignmentCase, *, source: str) -> dict[str, object]:
    interaction = build_chat_interaction_payload(case.message, source=source)
    route = _nested(interaction, "route")
    hint = awareness_route_hint(case.message)
    hint_context_card = _nested(_first_dict(hint.get("hints")), "workflow_context_card")
    observed = {
        "route_workflow": route.get("selected_skill"),
        "route_action": route.get("action"),
        "route_next_action": interaction.get("next_action"),
        "route_confidence": route.get("confidence"),
        "hint_status": hint.get("status"),
        "hint_workflow": hint.get("primary_workflow"),
        "hint_next_action": hint.get("primary_next_action"),
        "hint_context_card": hint_context_card.get("id", ""),
        "hint_claim_boundary": hint.get("claim_boundary"),
    }
    issues: list[str] = []
    if observed["route_workflow"] != case.expected_workflow:
        issues.append(f"expected route workflow {case.expected_workflow}, observed {observed['route_workflow']}")
    if observed["hint_status"] != "hinted":
        issues.append("missing awareness route hint")
    if observed["hint_workflow"] != case.expected_workflow:
        issues.append(f"expected hint workflow {case.expected_workflow}, observed {observed['hint_workflow'] or 'none'}")
    if observed["hint_workflow"] != observed["route_workflow"]:
        issues.append(f"route/hint mismatch: {observed['route_workflow']} != {observed['hint_workflow']}")
    if not observed["hint_context_card"]:
        issues.append("missing hint workflow context card")
    if "not workflow execution" not in str(observed["hint_claim_boundary"] or ""):
        issues.append("missing advisory-only hint boundary")
    return {
        "corpus": case.corpus,
        "id": case.id,
        "title": case.title,
        "message_sha256": hashlib.sha256(case.message.encode("utf-8")).hexdigest(),
        "aligned": not issues,
        "expected": {"workflow": case.expected_workflow},
        "observed": observed,
        "issues": issues,
    }


def _first_dict(value: object) -> dict[str, object]:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return {}


def _nested(payload: object, key: str) -> dict[str, object]:
    if isinstance(payload, dict):
        value = payload.get(key)
        return value if isinstance(value, dict) else {}
    return {}


def _dict_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]
