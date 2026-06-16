from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .local_store import atomic_write_json, ensure_dir, read_json_object, read_json_object_result, utc_now
from .paths import OmhPaths
from .skills.catalog import builtin_definitions


HERMES_OPS_BLUEPRINT_SCHEMA_VERSION = "hermes_ops_blueprint/v1"
HERMES_OPS_INDEX_SCHEMA_VERSION = "hermes_ops_blueprint_index/v1"
HERMES_OPS_VALIDATION_SCHEMA_VERSION = "hermes_ops_blueprint_validation/v1"
BLUEPRINT_KINDS = ("scheduled-ops-blueprint",)
BLUEPRINT_STATUSES = ("prepared", "blocked", "archived")
OBSERVATION_STATUSES = ("prepared", "not_observed")
BLUEPRINT_SUMMARY_LIMIT = 240
OBSERVED_CLAIM_STATUSES = {
    "observed",
    "complete",
    "completed",
    "ready",
    "sent",
    "delivered",
    "enabled",
    "executed",
    "loaded",
    "success",
    "succeeded",
}

PREPARED_IS_NOT_OBSERVED = (
    "A Hermes ops blueprint is projection metadata only. It is not host cron creation, gateway delivery, "
    "source retrieval, no-agent execution, plugin load, review, CI, merge-readiness, or merge evidence."
)
DEFAULT_NOT_EVIDENCE = (
    "host_cron_created",
    "hermes_automation_enabled",
    "gateway_delivery_sent",
    "source_retrieval_observed",
    "no_agent_script_written",
    "no_agent_execution",
    "plugin_loaded_by_hermes",
    "connector_invoked",
    "review",
    "ci",
    "merge_readiness",
    "merge",
)
OBSERVED_EVIDENCE_REQUIRED = (
    "Hermes host automation or cron listing that references the configured schedule.",
    "Gateway or Hermes message delivery record when delivery is claimed.",
    "Observed source retrieval or supplied source artifacts when research/report content is claimed.",
    "No-agent script/file/run evidence if a no-agent lane is later implemented.",
)
PROJECTION_SOURCE_REFS = (
    "src/skills/catalog.py",
    "src/catalogs/playbooks.py",
    "src/routing/recommend.py",
    "src/capabilities/orchestration.py",
    "src/operations.py",
)

_BLUEPRINT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,159}$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_TIME_RE = re.compile(
    r"\b(?:"
    r"at\s+(?:[01]?\d|2[0-3])(?::[0-5]\d)?\s*(?:am|pm)?"
    r"|(?:[01]?\d|2[0-3])(?::[0-5]\d)\s*(?:am|pm)?"
    r"|(?:[01]?\d|2[0-3])\s*(?:am|pm)"
    r")\b",
    re.IGNORECASE,
)
_EVERY_RE = re.compile(r"\b(every|each)\s+([a-z0-9 -]{1,40})", re.IGNORECASE)

_SCHEDULE_TERMS = {
    "daily": ("daily", "every day", "each day", "every morning", "매일", "毎日", "每天"),
    "weekday": ("weekday", "weekdays", "business day", "평일", "営業日", "工作日"),
    "weekly": ("weekly", "every week", "each week", "주간", "매주", "毎週", "每周"),
    "monthly": ("monthly", "every month", "each month", "월간", "매월", "毎月", "每月"),
    "morning": ("morning", "am", "아침", "오전", "朝", "上午"),
    "recurring": ("cron", "schedule", "scheduled", "recurring", "repeat", "heartbeat", "정기", "예약", "반복", "스케줄", "定期", "计划", "定时"),
}
_DELIVERY_SURFACES = {
    "discord": ("discord", "디스코드", "ディスコード"),
    "slack": ("slack", "슬랙", "スラック"),
    "telegram": ("telegram", "텔레그램", "テレグラム"),
    "email": ("email", "mail", "이메일", "メール", "邮箱"),
    "hermes-chat": ("chat", "thread", "same thread", "hermes", "대화", "스레드", "チャット", "聊天"),
}
_DELIVERY_TERMS = ("send", "post", "publish", "deliver", "notify", "share", "report to", "보내", "전송", "공유", "알림", "通知", "发送")
_SILENCE_TERMS = (
    "silent",
    "silently",
    "no reply",
    "do not reply",
    "only if changed",
    "only when changed",
    "only if something changed",
    "only when something changes",
    "if nothing changed",
    "if no change",
    "stay quiet",
    "변화 없으면",
    "바뀐 게 없으면",
    "조용히",
    "말하지",
    "응답하지",
    "変化がなければ",
    "静か",
    "没有变化",
    "保持安静",
)
_NO_AGENT_TERMS = (
    "watchdog",
    "heartbeat",
    "health check",
    "disk",
    "cpu",
    "memory",
    "ram",
    "nginx",
    "ping",
    "uptime",
    "threshold",
    "로그 감시",
    "상태 확인",
    "헬스체크",
)
_LLM_LIKELY_TERMS = (
    "summarize",
    "summary",
    "research",
    "sources",
    "competitor",
    "strategy",
    "brief",
    "memo",
    "회의",
    "조사",
    "리서치",
    "전략",
    "요약",
)


def build_scheduled_ops_blueprint(
    request: str,
    *,
    title: str = "",
    schedule: str = "",
    delivery: str = "",
    silence: str = "",
    source: str = "",
    blueprint_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    clean_request = " ".join(str(request).split())
    if not clean_request:
        raise ValueError("blueprint request is required")
    created = created_at or utc_now()
    skill_suggestions = _skill_suggestions(clean_request)
    schedule_intent = _schedule_intent(clean_request, schedule=schedule)
    delivery_intent = _delivery_intent(clean_request, delivery=delivery)
    silence_policy = _silence_policy(clean_request, silence=silence)
    no_agent_suitability = _no_agent_suitability(clean_request)
    prompt_outline = _prompt_outline(clean_request, skill_suggestions, schedule_intent, delivery_intent, silence_policy)
    record = {
        "schema_version": HERMES_OPS_BLUEPRINT_SCHEMA_VERSION,
        "blueprint_id": blueprint_id or new_hermes_ops_blueprint_id(clean_request, created),
        "kind": "scheduled-ops-blueprint",
        "title": title.strip() or _default_title(clean_request),
        "status": "prepared",
        "observation_status": "prepared",
        "created_at": created,
        "updated_at": created,
        "projection": {
            "authority": "projection_only",
            "derived_from": [
                "catalog skill metadata",
                "playbook metadata",
                "routing policy metadata",
                "capability pattern metadata",
                "operations artifact boundaries",
            ],
            "source_refs": list(PROJECTION_SOURCE_REFS),
        },
        "source": source.strip(),
        "request_summary": _preview(clean_request, limit=BLUEPRINT_SUMMARY_LIMIT),
        "schedule_intent": schedule_intent,
        "delivery_intent": delivery_intent,
        "silence_policy": silence_policy,
        "skill_suggestions": skill_suggestions,
        "context_chain": _context_chain(skill_suggestions),
        "no_agent_suitability": no_agent_suitability,
        "prompt_outline": prompt_outline,
        "wrapper_actions": [
            "show_blueprint",
            "revise_schedule",
            "confirm_delivery_policy",
            "prepare_host_schedule",
            "record_observed_runtime",
        ],
        "required_runtime_capabilities": [
            "Hermes automation or cron surface for recurring wakeups",
            "Hermes message/gateway surface when delivery outside the current chat is desired",
            "Observed source retrieval or supplied source artifacts for any report content",
        ],
        "optional_runtime_capabilities": [
            "No-agent watchdog runner for simple threshold checks",
            "Plugin hook status card if OMH plugin is installed and observed by Hermes",
            "Executor-neutral handoff if scheduled follow-up turns into coding work",
        ],
        "not_evidence_until_observed": list(DEFAULT_NOT_EVIDENCE),
        "observed_evidence_required": list(OBSERVED_EVIDENCE_REQUIRED),
        "prepared_is_not": PREPARED_IS_NOT_OBSERVED,
        "staged_gap_map": staged_gap_map(),
        "next_action": "Present the blueprint in Hermes, ask for schedule/delivery confirmation, then create host automation only outside this prepared artifact.",
        "status_card": _status_card(schedule_intent, delivery_intent, silence_policy, no_agent_suitability),
    }
    errors = validate_hermes_ops_blueprint(record)
    if errors:
        raise ValueError("; ".join(errors))
    return record


def new_hermes_ops_blueprint_id(request: str, now: datetime | str | None = None) -> str:
    stamp = _stamp(now)
    slug = _slugify(request)[:48] or "scheduled-ops"
    return f"{stamp}-scheduled-ops-{slug}-{secrets.token_hex(3)}"


def validate_hermes_ops_blueprint(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if record.get("schema_version") != HERMES_OPS_BLUEPRINT_SCHEMA_VERSION:
        errors.append("schema_version must be hermes_ops_blueprint/v1")
    if record.get("kind") not in BLUEPRINT_KINDS:
        errors.append(f"unsupported blueprint kind: {record.get('kind', '')}")
    blueprint_id = str(record.get("blueprint_id", ""))
    if not blueprint_id.strip():
        errors.append("blueprint_id is required")
    elif not _valid_blueprint_id(blueprint_id):
        errors.append("blueprint_id must contain only letters, digits, and hyphens, and must not contain path separators")
    if not str(record.get("title", "")).strip():
        errors.append("title is required")
    if record.get("status") not in BLUEPRINT_STATUSES:
        errors.append(f"unsupported blueprint status: {record.get('status', '')}")
    if record.get("observation_status") not in OBSERVATION_STATUSES:
        errors.append(f"unsupported blueprint observation_status: {record.get('observation_status', '')}")
    projection = record.get("projection")
    if not isinstance(projection, dict):
        errors.append("projection must be an object")
    else:
        if projection.get("authority") != "projection_only":
            errors.append("projection.authority must be projection_only")
        source_refs = projection.get("source_refs")
        if not isinstance(source_refs, list) or not source_refs:
            errors.append("projection.source_refs must be a non-empty list")
    for key in (
        "schedule_intent",
        "delivery_intent",
        "silence_policy",
        "no_agent_suitability",
        "prompt_outline",
        "status_card",
    ):
        if not isinstance(record.get(key), dict):
            errors.append(f"{key} must be an object")
    for key in (
        "skill_suggestions",
        "context_chain",
        "wrapper_actions",
        "required_runtime_capabilities",
        "optional_runtime_capabilities",
        "not_evidence_until_observed",
        "observed_evidence_required",
        "staged_gap_map",
    ):
        if not isinstance(record.get(key), list):
            errors.append(f"{key} must be a list")
    not_evidence = set(_string_list(record.get("not_evidence_until_observed", [])))
    if not set(DEFAULT_NOT_EVIDENCE).issubset(not_evidence):
        errors.append("not_evidence_until_observed must include the default prepared-vs-observed guard list")
    status_card = record.get("status_card")
    if isinstance(status_card, dict):
        status_not_observed = set(_string_list(status_card.get("not_observed", [])))
        if not set(DEFAULT_NOT_EVIDENCE).issubset(status_not_observed):
            errors.append("status_card.not_observed must include the default prepared-vs-observed guard list")
    if any(str(record.get(key, "")).lower() in {"observed", "complete", "ready"} for key in ("runtime_status", "delivery_status")):
        errors.append("blueprints must not claim observed runtime or delivery status")
    errors.extend(_nested_status_boundary_errors(record))
    return errors


def write_hermes_ops_blueprint(paths: OmhPaths, record: dict[str, Any]) -> dict[str, Any]:
    errors = validate_hermes_ops_blueprint(record)
    if errors:
        raise ValueError("; ".join(errors))
    blueprint_id = str(record["blueprint_id"])
    if hermes_ops_blueprint_exists(paths, blueprint_id):
        raise ValueError(f"Hermes ops blueprint already exists: {blueprint_id}")
    atomic_write_json(_blueprint_path(paths, blueprint_id), record, private=True)
    _write_index_cache(paths)
    return record


def list_hermes_ops_blueprints(paths: OmhPaths, *, limit: int | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for blueprint_path in sorted(paths.hermes_ops_blueprints_dir.glob("*.json")):
        record, error = read_json_object_result(blueprint_path)
        if error:
            continue
        if record:
            records.append(record)
    records.sort(key=lambda item: str(item.get("created_at", "")))
    if limit is not None:
        if limit < 1:
            return []
        records = records[-limit:]
    return records


def show_hermes_ops_blueprint(paths: OmhPaths, blueprint_id: str) -> dict[str, Any]:
    if not _valid_blueprint_id(blueprint_id):
        raise FileNotFoundError(blueprint_id)
    record = read_json_object(_blueprint_path(paths, blueprint_id))
    if record:
        return record
    raise FileNotFoundError(blueprint_id)


def summarize_hermes_ops_blueprint(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "blueprint_id": str(record.get("blueprint_id", "")),
        "kind": str(record.get("kind", "")),
        "title": str(record.get("title", "")),
        "status": str(record.get("status", "")),
        "observation_status": str(record.get("observation_status", "")),
        "updated_at": str(record.get("updated_at", "")),
        "schedule": str(record.get("schedule_intent", {}).get("cadence", "unspecified"))
        if isinstance(record.get("schedule_intent"), dict)
        else "unspecified",
        "delivery_surfaces": list(record.get("delivery_intent", {}).get("surfaces", []))
        if isinstance(record.get("delivery_intent"), dict)
        else [],
        "summary": _preview(str(record.get("request_summary", "")), limit=BLUEPRINT_SUMMARY_LIMIT),
    }


def validate_hermes_ops_store(paths: OmhPaths) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for blueprint_path in sorted(paths.hermes_ops_blueprints_dir.glob("*.json")):
        record, error = read_json_object_result(blueprint_path)
        if error:
            errors.append(f"{blueprint_path}: {error}")
            continue
        if record:
            records.append(record)
    for record in records:
        blueprint_id = str(record.get("blueprint_id", ""))
        if blueprint_id in seen:
            errors.append(f"duplicate blueprint_id: {blueprint_id}")
        seen.add(blueprint_id)
        for error in validate_hermes_ops_blueprint(record):
            errors.append(f"{blueprint_id or '<unknown>'}: {error}")
    index = read_json_object(paths.hermes_ops_index_path)
    if index and index.get("schema_version") != HERMES_OPS_INDEX_SCHEMA_VERSION:
        errors.append("Hermes ops index cache has unsupported schema_version")
    return {
        "schema_version": HERMES_OPS_VALIDATION_SCHEMA_VERSION,
        "ok": not errors,
        "blueprint_count": len(records),
        "errors": errors,
        "index_authority": "cache_only",
    }


def hermes_ops_blueprint_exists(paths: OmhPaths, blueprint_id: str) -> bool:
    return _valid_blueprint_id(blueprint_id) and _blueprint_path(paths, blueprint_id).exists()


def staged_gap_map() -> list[dict[str, str]]:
    return [
        {
            "gap": "automation_blueprints",
            "stage": "implemented",
            "scope": "scheduled-ops-blueprint projection for schedule, delivery, silence, and status-card guidance",
        },
        {
            "gap": "github_pr_issue_event_ops",
            "stage": "planned",
            "scope": "future projection over issue/PR event intake and review status",
        },
        {
            "gap": "durable_agent_board",
            "stage": "planned",
            "scope": "future board projection over multi-agent ownership and work lanes",
        },
        {
            "gap": "memory_curation",
            "stage": "planned",
            "scope": "future memory/skill curation review projection",
        },
        {
            "gap": "gateway_delivery_intent",
            "stage": "prepared_only",
            "scope": "delivery policy is prepared here; actual platform delivery requires observed Hermes/gateway evidence",
        },
        {
            "gap": "executor_runtime_readiness",
            "stage": "supported_elsewhere",
            "scope": "executor-neutral handoff and lifecycle artifacts remain separate from scheduled ops blueprints",
        },
        {
            "gap": "deliverable_packages",
            "stage": "supported_elsewhere",
            "scope": "materials-package and report-package own binary/deliverable QA boundaries",
        },
        {
            "gap": "voice_operator_guidance",
            "stage": "planned",
            "scope": "future chat/voice concise status card copy",
        },
        {
            "gap": "toolbelt_mcp_readiness",
            "stage": "supported_elsewhere",
            "scope": "MCP/tool readiness remains setup and probe metadata, not hidden tool execution",
        },
        {
            "gap": "observability_cost_latency_evidence",
            "stage": "partial",
            "scope": "status card lists missing evidence; full run/cost telemetry remains runtime-owned",
        },
    ]


def _schedule_intent(text: str, *, schedule: str = "") -> dict[str, object]:
    source = schedule.strip() or text
    folded = source.casefold()
    matches = []
    for label, terms in _SCHEDULE_TERMS.items():
        if any(term.casefold() in folded for term in terms):
            matches.append(label)
    every = _EVERY_RE.search(source)
    explicit_time = _TIME_RE.search(source)
    cadence = "unspecified"
    for candidate in ("daily", "weekday", "weekly", "monthly", "recurring"):
        if candidate in matches:
            cadence = candidate
            break
    if every and cadence == "unspecified":
        cadence = "recurring"
    return {
        "status": "prepared",
        "cadence": cadence,
        "explicit_schedule": schedule.strip(),
        "matched_terms": matches,
        "time_hint": explicit_time.group(0).strip() if explicit_time else "",
        "requires_confirmation": cadence == "unspecified" or not explicit_time,
    }


def _delivery_intent(text: str, *, delivery: str = "") -> dict[str, object]:
    source = f"{text} {delivery}".casefold()
    surfaces = [surface for surface, terms in _DELIVERY_SURFACES.items() if any(term.casefold() in source for term in terms)]
    if not surfaces and any(term.casefold() in source for term in _DELIVERY_TERMS):
        surfaces = ["hermes-chat"]
    if not surfaces:
        surfaces = ["current-hermes-thread"]
    return {
        "status": "prepared",
        "surfaces": surfaces,
        "explicit_delivery": delivery.strip(),
        "requires_observed_gateway_evidence": any(surface not in {"current-hermes-thread", "hermes-chat"} for surface in surfaces),
    }


def _silence_policy(text: str, *, silence: str = "") -> dict[str, object]:
    source = f"{text} {silence}".casefold()
    silent = bool(silence.strip()) or any(term.casefold() in source for term in _SILENCE_TERMS)
    return {
        "status": "prepared",
        "mode": "only_report_changes" if silent else "report_each_run",
        "explicit_policy": silence.strip(),
        "requires_confirmation": not silent,
    }


def _no_agent_suitability(text: str) -> dict[str, object]:
    folded = text.casefold()
    simple = any(term.casefold() in folded for term in _NO_AGENT_TERMS)
    llm_likely = any(term.casefold() in folded for term in _LLM_LIKELY_TERMS)
    if simple and not llm_likely:
        classification = "candidate"
        reason = "The request looks like a simple threshold/watchdog check that could later run without an LLM."
    elif simple and llm_likely:
        classification = "mixed"
        reason = "The request combines monitoring with synthesis; keep Hermes in the loop until evidence says otherwise."
    else:
        classification = "not_recommended"
        reason = "The request needs Hermes interpretation, source-backed synthesis, or status narration."
    return {
        "classification": classification,
        "reason": reason,
        "prepared_is_not_no_agent_execution": True,
    }


def _skill_suggestions(text: str) -> list[dict[str, str]]:
    available = {definition.name: definition for definition in builtin_definitions()}
    folded = text.casefold()
    candidates: list[tuple[str, str]] = [("automation-blueprint", "scheduled ops blueprint owner")]
    if any(term in folded for term in ("source", "sources", "research", "competitor", "news", "market", "조사", "리서치", "경쟁")):
        candidates.extend(
            [
                ("web-research", "fresh source retrieval lane when observed browsing is needed"),
                ("research-brief", "source-backed synthesis lane"),
            ]
        )
    if any(term in folded for term in ("report", "brief", "deck", "weekly", "monthly", "리포트", "보고", "자료")):
        candidates.append(("report-package", "report outline and delivery package lane"))
    if any(term in folded for term in ("incident", "slo", "error budget", "reliability", "장애", "에러버짓", "신뢰성")):
        candidates.append(("reliability-review", "incident/SLO evidence review lane"))
    if any(term in folded for term in ("feedback", "customer", "bug", "issue", "피드백", "고객", "버그", "이슈")):
        candidates.append(("feedback-triage", "customer signal clustering lane"))
    suggestions: list[dict[str, str]] = []
    seen: set[str] = set()
    for skill, reason in candidates:
        if skill in seen or skill not in available:
            continue
        seen.add(skill)
        definition = available[skill]
        suggestions.append(
            {
                "skill": skill,
                "phase": definition.phase,
                "hermes_role": definition.hermes_role,
                "reason": reason,
            }
        )
    return suggestions


def _context_chain(skill_suggestions: list[dict[str, str]]) -> list[str]:
    names = [str(item["skill"]) for item in skill_suggestions]
    chain = ["schedule_intent", "delivery_policy", "silence_policy"]
    if "web-research" in names or "research-brief" in names:
        chain.append("source_boundaries")
    if "report-package" in names:
        chain.append("report_outline")
    if "reliability-review" in names:
        chain.append("metric_or_incident_evidence")
    chain.extend(["not_evidence_boundary", "status_card"])
    return chain


def _prompt_outline(
    text: str,
    skill_suggestions: list[dict[str, str]],
    schedule_intent: dict[str, object],
    delivery_intent: dict[str, object],
    silence_policy: dict[str, object],
) -> dict[str, object]:
    skills = ", ".join(str(item["skill"]) for item in skill_suggestions) or "automation-blueprint"
    return {
        "system_intent": "Hermes should prepare a scheduled operation blueprint, not execute the schedule.",
        "operator_prompt": (
            f"Prepare scheduled ops for: {_preview(text, limit=160)}. "
            f"Use skills: {skills}. Cadence: {schedule_intent['cadence']}. "
            f"Delivery: {', '.join(str(item) for item in delivery_intent['surfaces'])}. "
            f"Silence mode: {silence_policy['mode']}. Keep prepared-vs-observed boundaries explicit."
        ),
        "missing_decisions": _missing_decisions(schedule_intent, delivery_intent, silence_policy),
    }


def _missing_decisions(
    schedule_intent: dict[str, object],
    delivery_intent: dict[str, object],
    silence_policy: dict[str, object],
) -> list[str]:
    missing = []
    if schedule_intent.get("requires_confirmation"):
        missing.append("confirm exact schedule/timezone")
    if delivery_intent.get("requires_observed_gateway_evidence"):
        missing.append("confirm Hermes/gateway delivery target and evidence source")
    if silence_policy.get("requires_confirmation"):
        missing.append("confirm whether to report every run or only changes")
    return missing


def _status_card(
    schedule_intent: dict[str, object],
    delivery_intent: dict[str, object],
    silence_policy: dict[str, object],
    no_agent_suitability: dict[str, object],
) -> dict[str, object]:
    return {
        "schema_version": "hermes_ops_status_card/v1",
        "headline": "Scheduled ops blueprint prepared",
        "prepared": [
            "schedule intent",
            "delivery policy",
            "silence policy",
            "skill/context chain",
            "evidence boundary",
        ],
        "not_observed": list(DEFAULT_NOT_EVIDENCE),
        "next": _missing_decisions(schedule_intent, delivery_intent, silence_policy)
        or ["record observed host automation only after Hermes/runtime evidence exists"],
        "no_agent_suitability": no_agent_suitability["classification"],
    }


def _default_title(text: str) -> str:
    return f"Scheduled ops: {_preview(text, limit=72)}"


def _blueprint_path(paths: OmhPaths, blueprint_id: str) -> Path:
    if not _valid_blueprint_id(blueprint_id):
        raise ValueError("blueprint_id must contain only letters, digits, and hyphens, and must not contain path separators")
    path = paths.hermes_ops_blueprints_dir / f"{blueprint_id}.json"
    root = paths.hermes_ops_blueprints_dir.resolve()
    resolved = path.resolve()
    if resolved.parent != root:
        raise ValueError("blueprint_id escapes Hermes ops storage")
    return path


def _write_index_cache(paths: OmhPaths) -> None:
    records = list_hermes_ops_blueprints(paths)
    ensure_dir(paths.hermes_ops_dir, private=True)
    atomic_write_json(
        paths.hermes_ops_index_path,
        {
            "schema_version": HERMES_OPS_INDEX_SCHEMA_VERSION,
            "updated_at": utc_now(),
            "authority": "cache_only",
            "blueprints": [summarize_hermes_ops_blueprint(record) for record in records],
        },
        private=True,
    )


def _stamp(value: datetime | str | None) -> str:
    if value is None:
        value = datetime.now(timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return _slugify(value)[:32] or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return _stamp(parsed)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _slugify(value: str) -> str:
    return (_SLUG_RE.sub("-", value.casefold()).strip("-") or "scheduled-ops")[:64].strip("-")


def _valid_blueprint_id(value: str) -> bool:
    return bool(_BLUEPRINT_ID_RE.fullmatch(str(value)))


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, tuple):
        value = list(value)
    if not isinstance(value, list):
        return [str(value).strip()] if str(value).strip() else []
    return [str(item).strip() for item in value if str(item).strip()]


def _nested_status_boundary_errors(value: object, *, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if path == "$" and key in {"status", "observation_status"}:
                continue
            if key == "status":
                status = str(child).casefold()
                if status not in OBSERVATION_STATUSES:
                    errors.append(f"{child_path} must remain prepared or not_observed")
            elif key.endswith("_status"):
                status = str(child).casefold()
                if status in OBSERVED_CLAIM_STATUSES:
                    errors.append(f"{child_path} must not claim observed runtime, delivery, execution, or integration evidence")
            errors.extend(_nested_status_boundary_errors(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_nested_status_boundary_errors(child, path=f"{path}[{index}]"))
    return errors


def _preview(value: str, *, limit: int) -> str:
    clean = " ".join(str(value).split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 3)].rstrip() + "..."
