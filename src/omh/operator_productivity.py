from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from typing import Any

from .local_store import atomic_write_json, read_json_object_result, utc_now
from .paths import OmhPaths


AGENT_OPERATOR_PRODUCTIVITY_SCHEMA_VERSION = "agent_operator_productivity/v1"
AGENT_OPERATOR_STATUS_CARD_SCHEMA_VERSION = "agent_operator_status_card/v1"
AGENT_OPERATOR_INDEX_SCHEMA_VERSION = "agent_operator_productivity_index/v1"
AGENT_OPERATOR_VALIDATION_SCHEMA_VERSION = "agent_operator_productivity_validation/v1"

CARD_KIND = "agent-ops-review"
CARD_STATUSES = ("prepared", "blocked", "archived")
OBSERVATION_STATUSES = ("prepared", "not_observed")
FOCUS_AREAS = ("auto", "mixed", "research", "coding", "review", "status")
SUMMARY_LIMIT = 240
PROJECTION_SOURCE_REFS = (
    "src/omh/operator_productivity.py",
    "src/omh/skills/catalog.py",
    "src/omh/routing/recommend.py",
    "src/omh/wrapper/contract.py",
    "src/omh/runtime/artifacts.py",
)
PREPARED_IS_NOT_OBSERVED = (
    "An agent ops review is projection metadata only. It is not source retrieval, executor dispatch, "
    "coding progress, implementation, review completion, verification, CI, merge-readiness, merge, "
    "platform delivery, provider billing, or live runtime telemetry evidence."
)
DEFAULT_NOT_EVIDENCE = (
    "source_retrieval_observed",
    "executor_dispatch_observed",
    "executor_session_attached",
    "implementation_observed",
    "verification_passed",
    "review_passed",
    "ci_passed",
    "merge_ready",
    "merge_observed",
    "platform_delivery_sent",
    "provider_cost_or_token_truth",
    "live_runtime_telemetry",
)
OBSERVED_EVIDENCE_REQUIRED = (
    "Observed source records or supplied source artifacts before claiming research findings.",
    "Runtime or wrapper observation before claiming executor dispatch, session attachment, or coding progress.",
    "Executor result records before claiming implementation completed.",
    "Verification, review, CI, and merge records before reporting those states as complete.",
    "Provider or host telemetry before reporting exact token, cost, latency, or queue truth.",
)
OBSERVED_CLAIM_STATUSES = {
    "observed",
    "complete",
    "completed",
    "ready",
    "passed",
    "success",
    "succeeded",
    "running",
    "dispatched",
    "attached",
    "merged",
    "delivered",
    "sent",
}

_CARD_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,159}$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")

_FOCUS_TERMS = {
    "research": (
        "research",
        "search",
        "source",
        "web",
        "market",
        "competitor",
        "paper",
        "조사",
        "리서치",
        "서치",
        "검색",
        "자료",
        "출처",
    ),
    "coding": (
        "coding",
        "code",
        "implement",
        "implementation",
        "codex",
        "claude",
        "executor",
        "handoff",
        "pr",
        "worktree",
        "worker",
        "코딩",
        "구현",
        "코드",
        "코덱스",
        "클로드",
        "위임",
        "작업",
    ),
    "review": (
        "review",
        "qa",
        "verify",
        "verification",
        "test",
        "ci",
        "quality",
        "gate",
        "리뷰",
        "검증",
        "테스트",
        "품질",
        "게이트",
    ),
    "status": (
        "status",
        "progress",
        "blocker",
        "blocked",
        "throughput",
        "productivity",
        "manager",
        "operator",
        "dashboard",
        "관리자",
        "진행",
        "상태",
        "막힘",
        "블로커",
        "생산량",
        "처리량",
    ),
}


def build_agent_operator_productivity_card(
    request: str,
    *,
    title: str = "",
    focus: str = "auto",
    source: str = "",
    card_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    clean_request = " ".join(str(request).split())
    if not clean_request:
        raise ValueError("agent ops review request is required")
    normalized_focus = _normalize_focus(focus)
    created = created_at or utc_now()
    detected_focus = _detect_focus(clean_request, normalized_focus)
    lanes = _quality_lanes(detected_focus)
    card = {
        "schema_version": AGENT_OPERATOR_PRODUCTIVITY_SCHEMA_VERSION,
        "card_id": card_id or new_agent_operator_productivity_card_id(clean_request, created),
        "kind": CARD_KIND,
        "title": title.strip() or _default_title(clean_request, detected_focus),
        "status": "prepared",
        "observation_status": "prepared",
        "created_at": created,
        "updated_at": created,
        "projection": {
            "authority": "projection_only",
            "derived_from": [
                "catalog skill metadata",
                "routing policy metadata",
                "wrapper chat contract",
                "runtime evidence ladder",
                "operations projection patterns",
            ],
            "source_refs": list(PROJECTION_SOURCE_REFS),
        },
        "source": source.strip(),
        "request_summary": _preview(clean_request, limit=SUMMARY_LIMIT),
        "manager_view": {
            "role": "third_party_operator",
            "goal": "maximize useful agent throughput without losing quality or evidence boundaries",
            "focus": detected_focus,
            "headline": _headline(detected_focus),
            "risk_level": _risk_level(detected_focus),
        },
        "workflow_quality": {
            "schema_version": "agent_workflow_quality/v1",
            "lanes": lanes,
            "readiness_summary": _readiness_summary(lanes),
            "quality_gate": "Do not advance a lane from prepared to observed without matching source, runtime, verification, review, CI, or merge evidence.",
        },
        "throughput_levers": _throughput_levers(detected_focus),
        "skill_chain": _skill_chain(detected_focus),
        "status_card": _status_card(detected_focus, lanes),
        "wrapper_actions": [
            "show_agent_ops_review",
            "choose_ops_lane",
            "prepare_research_lane",
            "prepare_coding_lane",
            "prepare_review_lane",
            "refresh_agent_ops_status",
            "record_agent_ops_observation",
            "show_status",
        ],
        "not_evidence_until_observed": list(DEFAULT_NOT_EVIDENCE),
        "observed_evidence_required": list(OBSERVED_EVIDENCE_REQUIRED),
        "prepared_is_not": PREPARED_IS_NOT_OBSERVED,
        "next_action": _next_action(detected_focus),
    }
    errors = validate_agent_operator_productivity_card(card)
    if errors:
        raise ValueError("; ".join(errors))
    return card


def new_agent_operator_productivity_card_id(request: str, now: datetime | str | None = None) -> str:
    stamp = _stamp(now)
    slug = _slugify(request)[:48] or "agent-ops-review"
    return f"{stamp}-agent-ops-{slug}-{secrets.token_hex(3)}"


def validate_agent_operator_productivity_card(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if record.get("schema_version") != AGENT_OPERATOR_PRODUCTIVITY_SCHEMA_VERSION:
        errors.append("schema_version must be agent_operator_productivity/v1")
    if record.get("kind") != CARD_KIND:
        errors.append(f"unsupported agent ops review kind: {record.get('kind', '')}")
    card_id = str(record.get("card_id", ""))
    if not card_id.strip():
        errors.append("card_id is required")
    elif not _valid_card_id(card_id):
        errors.append("card_id must contain only letters, digits, and hyphens, and must not contain path separators")
    if not str(record.get("title", "")).strip():
        errors.append("title is required")
    if record.get("status") not in CARD_STATUSES:
        errors.append(f"unsupported status: {record.get('status', '')}")
    if record.get("observation_status") not in OBSERVATION_STATUSES:
        errors.append(f"unsupported observation_status: {record.get('observation_status', '')}")
    projection = record.get("projection")
    if not isinstance(projection, dict):
        errors.append("projection must be an object")
    else:
        if projection.get("authority") != "projection_only":
            errors.append("projection.authority must be projection_only")
        source_refs = projection.get("source_refs")
        if not isinstance(source_refs, list) or not source_refs:
            errors.append("projection.source_refs must be a non-empty list")
    for key in ("manager_view", "workflow_quality", "status_card"):
        if not isinstance(record.get(key), dict):
            errors.append(f"{key} must be an object")
    for key in ("throughput_levers", "skill_chain", "wrapper_actions", "not_evidence_until_observed", "observed_evidence_required"):
        if not isinstance(record.get(key), list):
            errors.append(f"{key} must be a list")
    not_evidence = set(_string_list(record.get("not_evidence_until_observed", [])))
    if not set(DEFAULT_NOT_EVIDENCE).issubset(not_evidence):
        errors.append("not_evidence_until_observed must include the default agent ops guard list")
    status_card = record.get("status_card")
    if isinstance(status_card, dict):
        if status_card.get("schema_version") != AGENT_OPERATOR_STATUS_CARD_SCHEMA_VERSION:
            errors.append("status_card.schema_version must be agent_operator_status_card/v1")
        status_not_observed = set(_string_list(status_card.get("not_observed", [])))
        if not set(DEFAULT_NOT_EVIDENCE).issubset(status_not_observed):
            errors.append("status_card.not_observed must include the default agent ops guard list")
    errors.extend(_nested_observed_claim_errors(record))
    return errors


def write_agent_operator_productivity_card(paths: OmhPaths, record: dict[str, Any]) -> dict[str, Any]:
    errors = validate_agent_operator_productivity_card(record)
    if errors:
        raise ValueError("; ".join(errors))
    card_id = str(record["card_id"])
    if _card_path(paths, card_id).exists():
        raise ValueError(f"agent ops review already exists: {card_id}")
    atomic_write_json(_card_path(paths, card_id), record, private=True)
    _write_index_cache(paths)
    return record


def list_agent_operator_productivity_cards(paths: OmhPaths, *, limit: int | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for card_path in sorted(paths.agent_operator_productivity_cards_dir.glob("*.json")):
        record, error = read_json_object_result(card_path)
        if error:
            continue
        if record:
            records.append(record)
    records.sort(key=lambda item: str(item.get("created_at", "")))
    if limit is not None:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        return records[-limit:]
    return records


def show_agent_operator_productivity_card(paths: OmhPaths, card_id: str) -> dict[str, Any]:
    record, error = read_json_object_result(_card_path(paths, card_id))
    if error or record is None:
        raise FileNotFoundError(f"agent ops review not found: {card_id}")
    return record


def summarize_agent_operator_productivity_card(record: dict[str, Any]) -> dict[str, Any]:
    status_card = record.get("status_card", {}) if isinstance(record.get("status_card"), dict) else {}
    return {
        "schema_version": AGENT_OPERATOR_PRODUCTIVITY_SCHEMA_VERSION,
        "card_id": record.get("card_id", ""),
        "title": record.get("title", ""),
        "status": record.get("status", ""),
        "observation_status": record.get("observation_status", ""),
        "focus": (record.get("manager_view", {}) or {}).get("focus", ""),
        "created_at": record.get("created_at", ""),
        "next_action": record.get("next_action", ""),
        "quality_state": status_card.get("quality_state", ""),
        "blockers": list(status_card.get("blockers", [])) if isinstance(status_card.get("blockers"), list) else [],
    }


def validate_agent_operator_productivity_store(paths: OmhPaths) -> dict[str, Any]:
    errors: list[str] = []
    count = 0
    for card_path in sorted(paths.agent_operator_productivity_cards_dir.glob("*.json")):
        record, read_error = read_json_object_result(card_path)
        if read_error:
            errors.append(f"{card_path}: {read_error}")
            continue
        if record is None:
            continue
        count += 1
        for error in validate_agent_operator_productivity_card(record):
            errors.append(f"{card_path}: {error}")
    return {
        "schema_version": AGENT_OPERATOR_VALIDATION_SCHEMA_VERSION,
        "ok": not errors,
        "card_count": count,
        "errors": errors,
    }


def _write_index_cache(paths: OmhPaths) -> dict[str, Any]:
    cards = [summarize_agent_operator_productivity_card(record) for record in list_agent_operator_productivity_cards(paths)]
    payload = {
        "schema_version": AGENT_OPERATOR_INDEX_SCHEMA_VERSION,
        "updated_at": utc_now(),
        "count": len(cards),
        "cards": cards,
    }
    atomic_write_json(paths.agent_operator_productivity_index_path, payload, private=True)
    return payload


def _quality_lanes(focus: str) -> list[dict[str, Any]]:
    lane_ids = ["intake", "research", "coding", "review", "status"]
    lanes = [_lane(lane_id, focus) for lane_id in lane_ids]
    if focus == "research":
        return _prioritize(lanes, ("research", "status", "intake", "review", "coding"))
    if focus == "coding":
        return _prioritize(lanes, ("coding", "review", "status", "intake", "research"))
    if focus == "review":
        return _prioritize(lanes, ("review", "coding", "status", "intake", "research"))
    if focus == "status":
        return _prioritize(lanes, ("status", "intake", "coding", "review", "research"))
    return lanes


def _lane(lane_id: str, focus: str) -> dict[str, Any]:
    data = {
        "intake": {
            "label": "Intake and routing",
            "quality_gate": "Classify task shape before dispatch.",
            "missing_evidence": ["accepted workflow", "owner or executor choice"],
            "next_action": "choose workflow lane and stop condition",
            "throughput_lever": "Batch similar requests only after they share the same owner and verification gate.",
        },
        "research": {
            "label": "Research quality",
            "quality_gate": "Sources, freshness, conflicts, and retrieval gaps are named.",
            "missing_evidence": ["source_retrieval_observed", "source_quality_recorded"],
            "next_action": "prepare source boundaries or record observed sources",
            "throughput_lever": "Reuse source boundaries and brief templates across similar research tasks.",
        },
        "coding": {
            "label": "Coding delegation",
            "quality_gate": "Executor/runtime, acceptance criteria, and verification expectations are explicit.",
            "missing_evidence": ["executor_dispatch_observed", "executor_result_observed"],
            "next_action": "choose Codex, Claude Code, Hermes coding, or runtime handoff before dispatch",
            "throughput_lever": "Cache first-use executor readiness and split work only when file ownership is independent.",
        },
        "review": {
            "label": "Review and verification",
            "quality_gate": "Fast checks and slower review/CI gates are separated.",
            "missing_evidence": ["verification_passed", "review_passed", "ci_passed"],
            "next_action": "run or request the smallest proof that can advance the claim",
            "throughput_lever": "Use cheap inner checks frequently and reserve expensive review gates for risky changes.",
        },
        "status": {
            "label": "Manager status",
            "quality_gate": "Prepared, dispatched, executed, verified, reviewed, CI, and merge states stay separate.",
            "missing_evidence": ["live_runtime_telemetry", "runtime_observation_records"],
            "next_action": "refresh status from local artifacts or ask the wrapper to record observations",
            "throughput_lever": "Report blockers and next actions instead of re-running broad scans.",
        },
    }[lane_id]
    return {
        "lane": lane_id,
        "label": data["label"],
        "state": "prepared",
        "priority": "primary" if focus in {lane_id, "mixed"} or (focus == "coding" and lane_id == "review") else "supporting",
        "quality_gate": data["quality_gate"],
        "missing_evidence": data["missing_evidence"],
        "next_action": data["next_action"],
        "throughput_lever": data["throughput_lever"],
    }


def _prioritize(lanes: list[dict[str, Any]], order: tuple[str, ...]) -> list[dict[str, Any]]:
    rank = {lane: index for index, lane in enumerate(order)}
    return sorted(lanes, key=lambda lane: rank.get(str(lane.get("lane", "")), 999))


def _readiness_summary(lanes: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "overall": "prepared_not_observed",
        "primary_lanes": [lane["lane"] for lane in lanes if lane.get("priority") == "primary"],
        "blocking_gaps": sorted({gap for lane in lanes for gap in lane.get("missing_evidence", [])}),
        "manager_can_report": ["workflow choice", "quality gates", "missing evidence", "next action", "throughput levers"],
        "manager_cannot_report_yet": list(DEFAULT_NOT_EVIDENCE),
    }


def _status_card(focus: str, lanes: list[dict[str, Any]]) -> dict[str, Any]:
    blocking = sorted({gap for lane in lanes if lane.get("priority") == "primary" for gap in lane.get("missing_evidence", [])})
    return {
        "schema_version": AGENT_OPERATOR_STATUS_CARD_SCHEMA_VERSION,
        "headline": _headline(focus),
        "quality_state": "prepared_not_observed",
        "progress_summary": "Quality gates and next actions are ready; external runtime evidence has not been observed.",
        "blockers": blocking or ["accepted_workflow_or_observation_missing"],
        "next_action": _next_action(focus),
        "not_observed": list(DEFAULT_NOT_EVIDENCE),
        "small_copy": f"agent-ops: prepared({focus}) evidence:prepared_not_observed",
    }


def _skill_chain(focus: str) -> list[dict[str, str]]:
    chains = {
        "research": ("web-research", "research-brief", "research-department", "ops-observability-card"),
        "coding": ("executor-runtime-readiness", "plan", "ultraprocess", "code-review", "ops-observability-card"),
        "review": ("code-review", "ultraqa", "reliability-review", "ops-observability-card"),
        "status": ("agent-board", "ops-observability-card", "goal-execution", "executor-runtime-readiness"),
        "mixed": ("oh-my-hermes", "executor-runtime-readiness", "web-research", "code-review", "ops-observability-card"),
    }
    skills = chains.get(focus, chains["mixed"])
    return [{"skill": skill, "role": _skill_role(skill)} for skill in skills]


def _skill_role(skill: str) -> str:
    if skill in {"web-research", "research-brief", "research-department"}:
        return "research quality"
    if skill in {"executor-runtime-readiness", "plan", "ultraprocess"}:
        return "coding handoff quality"
    if skill in {"code-review", "ultraqa", "reliability-review"}:
        return "verification quality"
    if skill in {"agent-board", "ops-observability-card", "goal-execution"}:
        return "status and throughput"
    return "routing"


def _throughput_levers(focus: str) -> list[dict[str, str]]:
    base = [
        {
            "lever": "make the next action singular",
            "operator_value": "Less context switching; every update has one next step.",
            "guardrail": "Do not hide unresolved ownership or verification gaps.",
        },
        {
            "lever": "cache readiness after the first successful executor check",
            "operator_value": "Avoid repeating Codex, Claude Code, or runtime setup probes.",
            "guardrail": "Cached readiness is not dispatch or execution evidence.",
        },
        {
            "lever": "separate cheap checks from expensive gates",
            "operator_value": "Fast feedback stays fast; deep review runs only when it changes confidence.",
            "guardrail": "A cheap check cannot replace required review, CI, or semantic verification.",
        },
    ]
    if focus in {"research", "mixed"}:
        base.append(
            {
                "lever": "reuse source boundaries",
                "operator_value": "Recurring research work starts from known source scopes.",
                "guardrail": "Reused source boundaries are not fresh retrieval evidence.",
            }
        )
    if focus in {"coding", "review", "mixed"}:
        base.append(
            {
                "lever": "split only independent lanes",
                "operator_value": "Parallel work increases output when ownership and files do not collide.",
                "guardrail": "Parallel lane plans are not worker dispatch or result evidence.",
            }
        )
    return base


def _detect_focus(request: str, requested_focus: str) -> str:
    if requested_focus != "auto":
        return requested_focus
    value = request.lower()
    scores = {
        focus: sum(1 for term in terms if term.lower() in value)
        for focus, terms in _FOCUS_TERMS.items()
    }
    matched = [focus for focus, score in scores.items() if score > 0]
    if len(matched) > 1:
        return "mixed"
    if matched:
        return matched[0]
    return "mixed"


def _normalize_focus(value: str) -> str:
    normalized = str(value or "auto").strip().lower()
    if normalized not in FOCUS_AREAS:
        raise ValueError(f"unsupported focus: {value}")
    return normalized


def _headline(focus: str) -> str:
    return {
        "research": "Research quality and source evidence need management.",
        "coding": "Coding handoff, execution, and review gates need management.",
        "review": "Verification, review, and CI evidence need management.",
        "status": "Progress, blockers, and throughput need a manager view.",
        "mixed": "Research, coding, review, and status need one manager view.",
    }.get(focus, "Agent work needs one manager view.")


def _risk_level(focus: str) -> str:
    return "high" if focus in {"coding", "review", "mixed"} else "medium"


def _next_action(focus: str) -> str:
    return {
        "research": "prepare_research_lane",
        "coding": "prepare_coding_lane",
        "review": "prepare_review_lane",
        "status": "refresh_agent_ops_status",
        "mixed": "show_agent_ops_review",
    }.get(focus, "show_agent_ops_review")


def _default_title(request: str, focus: str) -> str:
    return f"Agent ops review: {focus} - {_preview(request, limit=72)}"


def _preview(value: str, *, limit: int) -> str:
    text = " ".join(str(value).split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."


def _slugify(value: str) -> str:
    slug = _SLUG_RE.sub("-", value.lower()).strip("-")
    return (slug or "agent-ops-review")[:64].strip("-") or "agent-ops-review"


def _stamp(value: datetime | str | None) -> str:
    if value is None:
        value = datetime.now(timezone.utc)
    if isinstance(value, str):
        return re.sub(r"[^0-9A-Za-z]+", "", value)[:24] or "00000000T000000Z"
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _valid_card_id(value: str) -> bool:
    return bool(_CARD_ID_RE.fullmatch(value)) and "/" not in value and "\\" not in value


def _card_path(paths: OmhPaths, card_id: str):
    if not _valid_card_id(str(card_id)):
        raise ValueError("agent ops review id must contain only letters, digits, and hyphens")
    return paths.agent_operator_productivity_cards_dir / f"{card_id}.json"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _nested_observed_claim_errors(value: Any, *, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            current_path = f"{path}.{key}"
            if str(key).lower() in {"status", "state", "observation_status", "quality_state", "delivery_status", "runtime_status"}:
                if str(item).strip().lower() in OBSERVED_CLAIM_STATUSES:
                    errors.append(f"{current_path} must not claim observed runtime or completion status")
            errors.extend(_nested_observed_claim_errors(item, path=current_path))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            errors.extend(_nested_observed_claim_errors(item, path=f"{path}[{index}]"))
    return errors
