from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from functools import lru_cache
import hashlib
from typing import Mapping, Sequence

from ..ingress import CHAT_SOURCES
from ..routing.action_copy import next_action_label
from ..routing.chat import route_chat_message


ROUTER_FAST_PATH_SCHEMA_VERSION = "router_fast_path/v1"


@dataclass(frozen=True)
class RouterFastPathCase:
    id: str
    title: str
    message: str
    expected_action: str
    expected_skill: str
    expected_next_action: str
    required_marker: str


# These are high-frequency chat-first turns where users feel latency most:
# picker entry, status, direct answers, file lookup, setup health, and common
# workflow surfaces. The gate is intentionally marker-based instead of
# wall-clock based so CI stays deterministic.
ROUTER_FAST_PATH_CASES: tuple[RouterFastPathCase, ...] = (
    RouterFastPathCase(
        "direct-picker",
        "Direct ./ picker opens without full workflow scoring",
        "./omh",
        "dispatch",
        "oh-my-hermes",
        "choose_skill",
        "direct_picker_alias",
    ),
    RouterFastPathCase(
        "status-slang-ko",
        "Korean short status slang opens agent ops fast path",
        "무슨일이노",
        "dispatch",
        "agent-ops-review",
        "prepare_agent_ops_review",
        "agent_ops_status_fast_path",
    ),
    RouterFastPathCase(
        "file-lookup-ko",
        "Korean file lookup stays on file lookup fast path",
        "README 내용 보여줘",
        "fallback",
        "oh-my-hermes",
        "answer_file_lookup",
        "file_lookup_fast_path",
    ),
    RouterFastPathCase(
        "thanks-direct",
        "Short thanks stays on direct-answer fast path",
        "thanks",
        "fallback",
        "oh-my-hermes",
        "answer_directly",
        "direct_answer_fast_path",
    ),
    RouterFastPathCase(
        "doctor-health-ko",
        "Korean update health question uses doctor fast path",
        "omh update 잘 된거야?",
        "dispatch",
        "doctor",
        "run_local_operator_check",
        "guard_fast_path:doctor_health_before_skill_catalog",
    ),
    RouterFastPathCase(
        "feedback-triage-ko",
        "Korean product issue goes to feedback triage fast path",
        "결제 실패 이슈가 자주 나와",
        "dispatch",
        "feedback-triage",
        "triage_feedback",
        "feedback_triage_fast_path",
    ),
    RouterFastPathCase(
        "coding-progress-ko",
        "Korean coding progress question uses coding status fast path",
        "코덱스가 지금 뭐하고 있어?",
        "dispatch",
        "ultraprocess",
        "show_coding_handoff_status",
        "guard_fast_path:coding_progress_status_before_clarify",
    ),
    RouterFastPathCase(
        "visual-summary-ko",
        "Korean image-card request uses visual operator fast path",
        "회의록을 예쁜 세로 이미지 카드로 만들어줘",
        "dispatch",
        "img-summary",
        "prepare_visual_prompt_card",
        "operator_surface_fast_path:visual",
    ),
    RouterFastPathCase(
        "scheduled-ops-ko",
        "Korean scheduled digest request uses automation fast path",
        "매일 아침 경쟁사 뉴스 요약해줘",
        "dispatch",
        "automation-blueprint",
        "prepare_scheduled_ops_blueprint",
        "operator_surface_fast_path:automation",
    ),
    RouterFastPathCase(
        "paper-learning-ko",
        "Korean paper explanation request uses paper fast path",
        "PDF 논문을 쉬운 난이도로 설명해줘",
        "dispatch",
        "paper-learning",
        "prepare_paper_learning",
        "operator_surface_fast_path:paper",
    ),
    RouterFastPathCase(
        "source-finder-ko",
        "Korean source acquisition request uses source fast path",
        "github repo랑 데이터셋 찾아줘",
        "dispatch",
        "source-finder",
        "prepare_source_finder_plan",
        "operator_surface_fast_path:source",
    ),
)


def build_router_fast_path_demo(*, source: str = "discord") -> dict[str, object]:
    if source not in CHAT_SOURCES:
        raise ValueError(f"unsupported demo source: {source}")
    return deepcopy(_build_router_fast_path_demo_cached(source))


@lru_cache(maxsize=8)
def _build_router_fast_path_demo_cached(source: str) -> dict[str, object]:
    rows = [_evaluate_case(case, source=source) for case in ROUTER_FAST_PATH_CASES]
    passing_count = sum(1 for row in rows if bool(row["passed"]))
    total = len(rows)
    missing_marker_count = sum(1 for row in rows if "missing_required_marker" in row["issues"])
    route_mismatch_count = sum(1 for row in rows if "route_mismatch" in row["issues"])
    next_action_mismatch_count = sum(1 for row in rows if "next_action_mismatch" in row["issues"])
    all_passing = bool(rows) and passing_count == total
    return {
        "schema_version": ROUTER_FAST_PATH_SCHEMA_VERSION,
        "source": source,
        "summary": {
            "case_count": total,
            "passing_count": passing_count,
            "missing_marker_count": missing_marker_count,
            "route_mismatch_count": route_mismatch_count,
            "next_action_mismatch_count": next_action_mismatch_count,
            "all_passing": all_passing,
        },
        "check_basis": [
            "High-frequency picker, status, direct-answer, file-lookup, and workflow requests keep explicit fast-path markers.",
            "Fast-path quality is deterministic route contract evidence, not wall-clock latency evidence.",
            "The gate fails if a common request falls back to full recommendation scoring or changes workflow/next-action unexpectedly.",
        ],
        "cases": rows,
        "claim_boundary": (
            "Router fast-path quality proves deterministic local fast-path route markers only. "
            "It does not prove wall-clock latency, live Hermes chat rendering, platform delivery, source retrieval, "
            "executor dispatch, implementation, verification, review, CI, merge, or plugin-load evidence."
        ),
    }


def format_router_fast_path_summary(payload: Mapping[str, object]) -> str:
    summary = _nested(payload, "summary")
    rows = _mapping_rows(payload.get("cases"))
    passing = int(summary.get("passing_count", 0) or 0)
    total = int(summary.get("case_count", len(rows)) or 0)
    lines = [
        "OMH router fast-path quality",
        f"Source: {payload.get('source', 'unknown')}",
        f"Result: {passing}/{total} fast-path cases passing",
        (
            f"Missing markers: {summary.get('missing_marker_count', 0)}; "
            f"route mismatches: {summary.get('route_mismatch_count', 0)}; "
            f"next-action mismatches: {summary.get('next_action_mismatch_count', 0)}"
        ),
        "",
        "What this proves:",
    ]
    for basis in _string_items(payload.get("check_basis")):
        lines.append(f"- {basis}")
    lines.extend(["", "Fast-path rollup:"])
    for row in rows:
        observed = _nested(row, "observed")
        status = "ok" if row.get("passed") else "needs attention"
        next_action = next_action_label(str(observed.get("next_action", "unknown")))
        lines.append(
            f"- {row.get('title', 'Untitled fast-path case')}: {status}; "
            f"{observed.get('route_action', 'unknown')} "
            f"{observed.get('selected_skill', 'unknown')} -> {next_action}; "
            f"marker={row.get('required_marker', '')}"
        )
    failed = [row for row in rows if not row.get("passed")]
    if failed:
        lines.extend(["", "Failures:"])
        for row in failed:
            lines.append(f"- {row.get('id', 'unknown')}: {', '.join(_string_items(row.get('issues'))) or 'unknown issue'}")
    lines.extend(
        [
            "",
            f"Boundary: {payload.get('claim_boundary', '')}",
            "Use --json for the full machine-readable payload.",
        ]
    )
    return "\n".join(lines)


def router_fast_path_errors(payload: Mapping[str, object]) -> list[str]:
    errors: list[str] = []
    if payload.get("schema_version") != ROUTER_FAST_PATH_SCHEMA_VERSION:
        errors.append("unexpected_schema")
    summary = _nested(payload, "summary")
    if not bool(summary.get("all_passing")):
        errors.append("not_all_fast_path_cases_passed")
    for key in ("missing_marker_count", "route_mismatch_count", "next_action_mismatch_count"):
        count = int(summary.get(key, 0) or 0)
        if count:
            errors.append(f"{key}: {count}")
    cases = payload.get("cases")
    if not isinstance(cases, Sequence) or isinstance(cases, (str, bytes)):
        errors.append("cases_not_sequence")
        return errors
    for case in cases:
        if not isinstance(case, Mapping) or bool(case.get("passed")):
            continue
        case_id = str(case.get("id") or "unknown")
        errors.append(f"{case_id}: {', '.join(_string_items(case.get('issues'))) or 'unknown fast-path failure'}")
    return errors


def _evaluate_case(case: RouterFastPathCase, *, source: str) -> dict[str, object]:
    route = route_chat_message(case.message, source=source, limit=3)
    recommendations = route.get("recommendations")
    top = recommendations[0] if isinstance(recommendations, list) and recommendations else {}
    if not isinstance(top, Mapping):
        top = {}
    matched = [str(item) for item in top.get("matched", []) if str(item)]
    observed = {
        "route_action": str(route.get("action", "")),
        "selected_skill": str(route.get("selected_skill", "")),
        "selected_harness": str(route.get("selected_harness", "")),
        "next_action": str(top.get("next_action", "")),
        "matched": matched,
        "score": top.get("score", route.get("score", 0)),
    }
    issues: list[str] = []
    if observed["route_action"] != case.expected_action:
        issues.append("route_mismatch")
    if observed["selected_skill"] != case.expected_skill:
        issues.append("skill_mismatch")
    if observed["next_action"] != case.expected_next_action:
        issues.append("next_action_mismatch")
    if case.required_marker not in matched:
        issues.append("missing_required_marker")
    return {
        "id": case.id,
        "title": case.title,
        "message_sha256": _message_sha256(case.message),
        "expected": {
            "route_action": case.expected_action,
            "selected_skill": case.expected_skill,
            "next_action": case.expected_next_action,
        },
        "required_marker": case.required_marker,
        "observed": observed,
        "passed": not issues,
        "issues": issues,
    }


def _message_sha256(message: str) -> str:
    return hashlib.sha256(message.encode("utf-8")).hexdigest()


def _nested(payload: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = payload.get(key)
    return value if isinstance(value, Mapping) else {}


def _mapping_rows(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [row for row in value if isinstance(row, Mapping)]


def _string_items(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value if str(item)]
