from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from ..context import build_context_brief
from ..ingress import CHAT_SOURCES


CONTEXT_BRIEF_COVERAGE_SCHEMA_VERSION = "context_brief_coverage/v1"


@dataclass(frozen=True)
class ContextBriefCoverageCase:
    id: str
    title: str
    message: str
    expected_workflow: str
    expected_next_action: str
    expected_catalog_question: bool = False
    sensitive_token: str = ""


# Frozen first-turn corpus for the Hermes-facing context rail. These cases
# protect the moment where Hermes should remember OMH before using generic
# image, search, file, chat, or coding tools.
CONTEXT_BRIEF_COVERAGE_CASES: tuple[ContextBriefCoverageCase, ...] = (
    ContextBriefCoverageCase(
        "visual-summary-before-image-tool",
        "Visual summary before generic image tools",
        "make an image card for this PR with secret-token-123",
        "img-summary",
        "prepare_visual_prompt_card",
        sensitive_token="secret-token-123",
    ),
    ContextBriefCoverageCase(
        "catalog-picker-without-shell-approval",
        "Catalog picker without shell approval",
        "what OMH workflows are available?",
        "",
        "show_workflow_picker",
        expected_catalog_question=True,
    ),
    ContextBriefCoverageCase(
        "feedback-triage-before-coding",
        "Customer feedback before coding",
        "결제 실패 이슈가 자주 나와",
        "feedback-triage",
        "classify_signal_and_prepare_investigation",
    ),
    ContextBriefCoverageCase(
        "github-issue-to-pr",
        "GitHub issue to PR operations",
        "turn this GitHub issue into a PR-ready plan",
        "github-event-ops",
        "prepare_github_event_ops_card",
    ),
    ContextBriefCoverageCase(
        "paper-learning",
        "Paper learning",
        "논문 PDF를 쉬운 수준으로 섹션별로 해설해줘",
        "paper-learning",
        "prepare_paper_learning",
    ),
    ContextBriefCoverageCase(
        "source-finder",
        "Source finder",
        "find papers datasets github repos and public presentations about agent memory",
        "source-finder",
        "prepare_source_finder_plan",
    ),
    ContextBriefCoverageCase(
        "safe-feature-plan",
        "Safe feature plan",
        "I want to safely add a feature to this repo",
        "ralplan",
        "present_plan",
    ),
    ContextBriefCoverageCase(
        "web-research",
        "Source-backed web research",
        "web research with citations about current AI agent market trends",
        "web-research",
        "gather_source_backed_evidence",
    ),
)


def build_context_brief_coverage_demo(*, source: str = "discord") -> dict[str, object]:
    if source not in CHAT_SOURCES:
        raise ValueError(f"unsupported demo source: {source}")
    rows = [_evaluate_context_brief_case(case, source=source) for case in CONTEXT_BRIEF_COVERAGE_CASES]
    passing_count = sum(1 for row in rows if bool(row["passed"]))
    route_hint_count = sum(1 for row in rows if row["observed"]["route_hint_status"] == "hinted")
    catalog_count = sum(1 for row in rows if bool(row["observed"]["catalog_question"]))
    return {
        "schema_version": CONTEXT_BRIEF_COVERAGE_SCHEMA_VERSION,
        "source": source,
        "summary": {
            "case_count": len(rows),
            "passing_count": passing_count,
            "route_hint_count": route_hint_count,
            "catalog_question_count": catalog_count,
            "all_passing": bool(rows) and passing_count == len(rows),
        },
        "check_basis": [
            "The context brief is metadata-only and does not echo or store raw prompts.",
            "Catalog questions produce a picker hint instead of shell-command approval.",
            "Workflow-like requests include a matching route hint and next action.",
            "Prompt context includes bounded OMH awareness and message-specific route hints when available.",
            "Generic-tool checkpoint, normal response contract, and claim boundary remain visible.",
            "This gate checks local Hermes-facing context only; it does not prove live Hermes selection or execution.",
        ],
        "cases": rows,
        "claim_boundary": (
            "Context brief coverage proves deterministic local OMH mental-model and route-hint contracts only. "
            "It does not prove live Hermes chat rendering, plugin load, generic tool invocation, image generation, "
            "source retrieval, executor dispatch, implementation, verification, review, CI, merge, or delivery."
        ),
    }


def format_context_brief_coverage_summary(payload: dict[str, object]) -> str:
    summary = _nested(payload, "summary")
    rows = _dict_rows(payload.get("cases", []))
    total = int(summary.get("case_count", len(rows)) or 0)
    passing = int(summary.get("passing_count", 0) or 0)
    hinted = int(summary.get("route_hint_count", 0) or 0)
    catalog = int(summary.get("catalog_question_count", 0) or 0)
    all_passing = bool(summary.get("all_passing", False))
    lines = [
        "OMH context brief coverage",
        f"Source: {payload.get('source', 'unknown')}",
        f"Result: {passing}/{total} context brief cases passing" + (" (all passing)" if all_passing else ""),
        f"Route hints: {hinted}; catalog picker hints: {catalog}",
        "",
        "What this proves:",
    ]
    for basis in payload.get("check_basis", []):
        lines.append(f"- {basis}")
    lines.extend(["", "Context rollup:"])
    for row in rows:
        observed = _nested(row, "observed")
        status = "ok" if row.get("passed") else "needs attention"
        workflow = observed.get("primary_workflow") or "catalog"
        action = observed.get("primary_next_action") or observed.get("catalog_next_action") or "unknown"
        lines.append(f"- {row.get('title', 'Untitled context')}: {status}; {workflow} -> {action}")
    failed = [row for row in rows if not row.get("passed")]
    if failed:
        lines.extend(["", "Failures:"])
        for row in failed:
            lines.append(f"- {row.get('id', 'unknown')}: {', '.join(row.get('issues', [])) or 'unknown issue'}")
    lines.extend(
        [
            "",
            f"Boundary: {payload.get('claim_boundary', '')}",
            "Use --json for the full machine-readable payload.",
        ]
    )
    return "\n".join(lines)


def _evaluate_context_brief_case(case: ContextBriefCoverageCase, *, source: str) -> dict[str, object]:
    brief = build_context_brief(case.message, source=source, include_prompt_context=True)
    route_hint = _nested(brief, "route_hint")
    catalog_question = _nested(brief, "catalog_question")
    first_hint = _first_dict(route_hint.get("hints"))
    prompt_context = str(brief.get("prompt_context") or "")
    serialized = json.dumps(brief, sort_keys=True, ensure_ascii=False)
    observed = {
        "schema_version": brief.get("schema_version"),
        "source": brief.get("source"),
        "route_hint_status": route_hint.get("status"),
        "primary_workflow": route_hint.get("primary_workflow"),
        "primary_next_action": route_hint.get("primary_next_action"),
        "hint_count": len(_dict_rows(route_hint.get("hints", []))),
        "workflow_context_card": bool(_nested(first_hint, "workflow_context_card")),
        "catalog_question": bool(catalog_question),
        "catalog_next_action": catalog_question.get("next_action"),
        "catalog_recommended_tool": catalog_question.get("recommended_tool"),
        "generic_tool_checkpoint": _nested(brief, "generic_tool_checkpoint").get("schema_version"),
        "normal_response_contract": _nested(brief, "normal_response_contract").get("schema_version"),
        "capability_family_count": len(_dict_rows(brief.get("capability_families", []))),
        "prompt_context_included": bool(prompt_context),
        "prompt_context_has_primer": "[OMH Awareness]" in prompt_context,
        "prompt_context_has_route_hint": "[OMH Route Hint]" in prompt_context,
        "raw_prompt_stored": _nested(brief, "message").get("raw_prompt_stored"),
        "raw_prompt_echoed": _nested(brief, "message").get("raw_prompt_echoed"),
        "sensitive_token_leaked": bool(case.sensitive_token and case.sensitive_token in serialized),
        "claim_boundary": brief.get("claim_boundary"),
    }
    issues: list[str] = []
    if observed["schema_version"] != "omh_context_brief/v1":
        issues.append(f"unexpected schema {observed['schema_version']}")
    if observed["source"] != source:
        issues.append(f"unexpected source {observed['source']}")
    if observed["raw_prompt_stored"] is not False:
        issues.append("raw prompt stored flag is not false")
    if observed["raw_prompt_echoed"] is not False:
        issues.append("raw prompt echoed flag is not false")
    if observed["sensitive_token_leaked"]:
        issues.append("sensitive token leaked")
    if observed["generic_tool_checkpoint"] != "omh_generic_tool_checkpoint/v1":
        issues.append("missing generic tool checkpoint")
    if observed["normal_response_contract"] != "omh_context_response_contract/v1":
        issues.append("missing normal response contract")
    if int(observed["capability_family_count"] or 0) < 5:
        issues.append("missing capability family context")
    if not str(observed["claim_boundary"] or "").strip():
        issues.append("missing claim boundary")
    if not observed["prompt_context_included"] or not observed["prompt_context_has_primer"]:
        issues.append("missing bounded prompt context primer")

    if case.expected_catalog_question:
        if not observed["catalog_question"]:
            issues.append("missing catalog question hint")
        if observed["catalog_next_action"] != case.expected_next_action:
            issues.append(
                f"expected catalog next action {case.expected_next_action}, observed {observed['catalog_next_action']}"
            )
        if observed["catalog_recommended_tool"] != "omh_capabilities":
            issues.append(f"expected omh_capabilities, observed {observed['catalog_recommended_tool']}")
    else:
        if observed["route_hint_status"] != "hinted":
            issues.append(f"expected hinted route, observed {observed['route_hint_status']}")
        if observed["primary_workflow"] != case.expected_workflow:
            issues.append(f"expected workflow {case.expected_workflow}, observed {observed['primary_workflow']}")
        if observed["primary_next_action"] != case.expected_next_action:
            issues.append(
                f"expected next action {case.expected_next_action}, observed {observed['primary_next_action']}"
            )
        if int(observed["hint_count"] or 0) < 1:
            issues.append("missing route hints")
        if not observed["workflow_context_card"]:
            issues.append("missing workflow context card")
        if not observed["prompt_context_has_route_hint"]:
            issues.append("missing message-specific route hint prompt context")
        if f"selected={case.expected_workflow}" not in prompt_context:
            issues.append("prompt context does not name selected workflow")

    return {
        "id": case.id,
        "title": case.title,
        "message_sha256": hashlib.sha256(case.message.encode("utf-8")).hexdigest(),
        "passed": not issues,
        "expected": {
            "workflow": case.expected_workflow,
            "next_action": case.expected_next_action,
            "catalog_question": case.expected_catalog_question,
        },
        "observed": observed,
        "issues": issues,
    }


def _nested(payload: dict[str, object], key: str) -> dict[str, object]:
    value = payload.get(key)
    return value if isinstance(value, dict) else {}


def _dict_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _first_dict(value: object) -> dict[str, object]:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return {}
