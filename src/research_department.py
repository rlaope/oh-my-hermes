from __future__ import annotations

import re
import secrets
from datetime import datetime, timezone
from typing import Any

from .local_store import atomic_write_json, ensure_dir, read_json_object, read_json_object_result, utc_now
from .paths import OmhPaths


RESEARCH_DEPARTMENT_PLAN_SCHEMA_VERSION = "research_department_plan/v1"
SOURCE_INBOX_SCHEMA_VERSION = "source_inbox/v1"
BRIEFING_STATUS_SCHEMA_VERSION = "briefing_status/v1"
RESEARCH_DEPARTMENT_INDEX_SCHEMA_VERSION = "research_department_index/v1"
RESEARCH_DEPARTMENT_VALIDATION_SCHEMA_VERSION = "research_department_validation/v1"

PLAN_KIND = "research-department-workflow"
PLAN_STATUSES = ("prepared", "blocked", "archived")
OBSERVATION_STATUSES = ("prepared", "not_observed")
PLAN_SUMMARY_LIMIT = 240
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
    "verified",
    "fetched",
    "retrieved",
    "written",
}

PREPARED_IS_NOT_OBSERVED = (
    "A research-department plan is projection metadata only. It is not source retrieval, "
    "synthesis-tool execution, knowledge-store writes, host cron creation, gateway delivery, human "
    "verification, connector invocation, or brief delivery evidence."
)
DEFAULT_NOT_EVIDENCE = (
    "source_retrieval_observed",
    "synthesis_tool_query_observed",
    "synthesis_tool_workspace_created",
    "knowledge_store_write_observed",
    "host_cron_created",
    "hermes_automation_enabled",
    "gateway_delivery_sent",
    "brief_delivered",
    "human_verification_complete",
    "paywall_or_access_resolved",
    "conflict_resolution_complete",
    "connector_invoked",
)
LEGACY_NOT_EVIDENCE_ALIASES = {
    "synthesis_tool_query_observed": ("notebooklm_query_executed",),
    "synthesis_tool_workspace_created": ("notebooklm_notebook_created",),
    "knowledge_store_write_observed": ("obsidian_vault_written",),
}
OBSERVED_EVIDENCE_REQUIRED = (
    "Observed source retrieval records or supplied source artifacts before claiming collected findings.",
    "Observed synthesis-tool output before claiming knowledge summarization or workspace queries.",
    "Observed knowledge-store write records before claiming persistent notes, inboxes, or briefs were saved.",
    "Hermes host automation or cron listing before claiming scheduled wakeups.",
    "Gateway or Hermes message delivery record before claiming a brief was delivered.",
    "Human or verifier review record before claiming conflicts or source quality are verified.",
)
PROJECTION_SOURCE_REFS = (
    "src/research_department.py",
    "src/skills/catalog.py",
    "src/routing/recommend.py",
    "src/capabilities/orchestration.py",
    "src/hermes_ops.py",
)

_PLAN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,159}$")
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_EVERY_RE = re.compile(r"\b(every|each)\s+([a-z0-9 -]{1,40})", re.IGNORECASE)
_TOPIC_PREFIX_RE = re.compile(
    r"\b(?:about|for|on|regarding)\s+([a-z0-9][a-z0-9 ,._/-]{2,80})",
    re.IGNORECASE,
)

_CADENCE_TERMS = {
    "daily": ("daily", "every day", "each day", "every morning", "매일", "毎日", "每天"),
    "weekday": ("weekday", "weekdays", "business day", "평일", "営業日", "工作日"),
    "weekly": ("weekly", "every week", "each week", "매주", "주간", "毎週", "每周"),
    "monthly": ("monthly", "every month", "each month", "매월", "월간", "毎月", "每月"),
    "durable": ("ongoing", "24/7", "always on", "durable", "계속", "지속", "상시"),
    "one_off": ("one-off", "one time", "once", "한번", "한 번"),
}
_DELIVERY_SURFACES = {
    "discord": ("discord", "디스코드", "ディスコード"),
    "slack": ("slack", "슬랙", "スラック"),
    "telegram": ("telegram", "텔레그램", "テレグラム"),
    "email": ("email", "mail", "이메일", "メール", "邮箱"),
    "report": ("report", "brief", "digest", "리포트", "보고", "브리핑", "ダイジェスト", "简报"),
}
_SOURCE_TYPES = {
    "competitor": ("competitor", "competitive", "경쟁사", "경쟁", "競合", "竞争"),
    "market": ("market", "industry", "시장", "산업", "市場", "行业"),
    "news": ("news", "press", "뉴스", "소식", "ニュース", "新闻"),
    "papers": ("paper", "papers", "research paper", "논문", "論文", "论文"),
    "customer": ("customer", "feedback", "고객", "피드백", "顧客", "客户"),
    "internal": ("docs", "notebook", "vault", "internal", "문서", "노트", "資料", "文档"),
}


def build_research_department_plan(
    request: str,
    *,
    title: str = "",
    topic: str = "",
    cadence: str = "",
    delivery: str = "",
    storage: str = "",
    knowledge_store: str = "",
    synthesis_tool: str = "",
    source: str = "",
    sources: list[str] | None = None,
    notebooklm: str = "unknown",
    obsidian: str = "unknown",
    plan_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    clean_request = " ".join(str(request).split())
    if not clean_request:
        raise ValueError("research department request is required")
    created = created_at or utc_now()
    record_id = plan_id or new_research_department_plan_id(clean_request, created)
    source_policy = _source_policy(clean_request, sources=sources or [])
    source_inbox = build_source_inbox(plan_id=record_id, created_at=created)
    briefing_status = build_briefing_status(plan_id=record_id, source_inbox=source_inbox, created_at=created)
    roles = _role_lanes()
    skill_chain = _skill_chain(source_policy)
    knowledge_store_intent = _knowledge_store_intent(
        clean_request,
        storage=storage,
        knowledge_store=knowledge_store,
        obsidian=obsidian,
    )
    synthesis_tool_intent = _synthesis_tool_intent(
        clean_request,
        synthesis_tool=synthesis_tool,
        notebooklm=notebooklm,
    )
    record = {
        "schema_version": RESEARCH_DEPARTMENT_PLAN_SCHEMA_VERSION,
        "plan_id": record_id,
        "kind": PLAN_KIND,
        "title": title.strip() or _default_title(clean_request),
        "status": "prepared",
        "observation_status": "prepared",
        "created_at": created,
        "updated_at": created,
        "projection": {
            "authority": "projection_only",
            "derived_from": [
                "catalog skill metadata",
                "routing policy metadata",
                "scheduled ops blueprint boundaries",
                "Hermes-facing research workflow patterns",
            ],
            "source_refs": list(PROJECTION_SOURCE_REFS),
        },
        "source": source.strip(),
        "request_summary": _preview(clean_request, limit=PLAN_SUMMARY_LIMIT),
        "topic_intent": _topic_intent(clean_request, topic=topic),
        "cadence_intent": _cadence_intent(clean_request, cadence=cadence),
        "delivery_intent": _delivery_intent(clean_request, delivery=delivery),
        "knowledge_store": knowledge_store_intent,
        "synthesis_tool": synthesis_tool_intent,
        "source_policy": source_policy,
        "roles": roles,
        "skill_chain": skill_chain,
        "workflow_chain": _workflow_chain(roles),
        "source_inbox": source_inbox,
        "briefing_status": briefing_status,
        "optional_integrations": {
            "knowledge_store": knowledge_store_intent,
            "synthesis_tool": synthesis_tool_intent,
        },
        "prompt_outline": _prompt_outline(clean_request, skill_chain),
        "wrapper_actions": [
            "show_research_department_plan",
            "revise_topic_or_sources",
            "confirm_cadence_delivery_tooling",
            "prepare_scout_research",
            "prepare_analyst_synthesis",
            "prepare_briefer_output",
            "record_observed_source_or_delivery_evidence",
        ],
        "required_runtime_capabilities": [
            "Hermes research workflow skills for source scoping, synthesis, and status narration.",
            "Observed source retrieval or supplied source artifacts before content claims.",
            "A Hermes/governed scheduler only if the operator wants recurring wakeups.",
        ],
        "optional_runtime_capabilities": [
            "A synthesis tool for curated knowledge summarization when the operator has configured one.",
            "A knowledge store for persistent source inboxes, notes, and briefs when the operator has configured one.",
            "Gateway delivery evidence when briefs leave the current Hermes thread.",
        ],
        "not_evidence_until_observed": list(DEFAULT_NOT_EVIDENCE),
        "observed_evidence_required": list(OBSERVED_EVIDENCE_REQUIRED),
        "prepared_is_not": PREPARED_IS_NOT_OBSERVED,
        "next_action": (
            "Present the research department plan in Hermes, confirm topic/source/cadence/tooling, "
            "then record source retrieval, synthesis-tool output, knowledge-store writes, and delivery only from observed evidence."
        ),
    }
    errors = validate_research_department_plan(record)
    if errors:
        raise ValueError("; ".join(errors))
    return record


def build_source_inbox(
    *,
    plan_id: str,
    created_at: str | None = None,
    raw_findings: list[dict[str, Any]] | None = None,
    processed_notes: list[dict[str, Any]] | None = None,
    briefs: list[dict[str, Any]] | None = None,
    conflicts: list[dict[str, Any]] | None = None,
    needs_verification: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now()
    buckets = {
        "raw_findings": _inbox_bucket(raw_findings),
        "processed_notes": _inbox_bucket(processed_notes),
        "briefs": _inbox_bucket(briefs),
        "conflicts": _inbox_bucket(conflicts),
        "needs_verification": _inbox_bucket(needs_verification),
    }
    return {
        "schema_version": SOURCE_INBOX_SCHEMA_VERSION,
        "plan_id": str(plan_id),
        "created_at": created,
        "updated_at": created,
        "authority": "projection_only",
        "buckets": buckets,
        "counts": {name: len(bucket["items"]) for name, bucket in buckets.items()},
        "boundary": "Empty or prepared inbox buckets are not source retrieval, synthesis, storage, or verification evidence.",
    }


def build_briefing_status(
    *,
    plan_id: str,
    source_inbox: dict[str, Any],
    created_at: str | None = None,
) -> dict[str, Any]:
    created = created_at or utc_now()
    counts = source_inbox.get("counts", {}) if isinstance(source_inbox.get("counts"), dict) else {}
    raw_count = int(counts.get("raw_findings", 0) or 0)
    note_count = int(counts.get("processed_notes", 0) or 0)
    brief_count = int(counts.get("briefs", 0) or 0)
    conflict_count = int(counts.get("conflicts", 0) or 0)
    verification_count = int(counts.get("needs_verification", 0) or 0)
    return {
        "schema_version": BRIEFING_STATUS_SCHEMA_VERSION,
        "plan_id": str(plan_id),
        "created_at": created,
        "updated_at": created,
        "headline": "Research department workflow prepared",
        "lanes": {
            "scout": {"status": "not_observed", "prepared_role": "collect source candidates", "count": raw_count},
            "analyst": {"status": "not_observed", "prepared_role": "synthesize processed notes", "count": note_count},
            "briefer": {"status": "not_observed", "prepared_role": "prepare brief output", "count": brief_count},
            "verification": {
                "status": "not_observed",
                "prepared_role": "flag conflicts and source-quality gaps",
                "conflicts": conflict_count,
                "needs_verification": verification_count,
            },
        },
        "summary_counts": {
            "collected": raw_count,
            "processed": note_count,
            "briefed": brief_count,
            "conflicts": conflict_count,
            "needs_verification": verification_count,
        },
        "not_observed": list(DEFAULT_NOT_EVIDENCE),
        "next": [
            "confirm topic, source boundaries, cadence, delivery, and storage",
            "record observed source retrieval before claiming collected findings",
            "record observed synthesis or human review before marking briefs verified",
        ],
    }


def new_research_department_plan_id(request: str, now: datetime | str | None = None) -> str:
    stamp = _stamp(now)
    slug = _slugify(request)[:48] or "research-department"
    return f"{stamp}-research-department-{slug}-{secrets.token_hex(3)}"


def validate_research_department_plan(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if record.get("schema_version") != RESEARCH_DEPARTMENT_PLAN_SCHEMA_VERSION:
        errors.append("schema_version must be research_department_plan/v1")
    if record.get("kind") != PLAN_KIND:
        errors.append(f"unsupported research department kind: {record.get('kind', '')}")
    plan_id = str(record.get("plan_id", ""))
    if not plan_id.strip():
        errors.append("plan_id is required")
    elif not _valid_plan_id(plan_id):
        errors.append("plan_id must contain only letters, digits, and hyphens, and must not contain path separators")
    if not str(record.get("title", "")).strip():
        errors.append("title is required")
    if record.get("status") not in PLAN_STATUSES:
        errors.append(f"unsupported research department status: {record.get('status', '')}")
    if record.get("observation_status") not in OBSERVATION_STATUSES:
        errors.append(f"unsupported research department observation_status: {record.get('observation_status', '')}")
    projection = record.get("projection")
    if not isinstance(projection, dict):
        errors.append("projection must be an object")
    else:
        if projection.get("authority") != "projection_only":
            errors.append("projection.authority must be projection_only")
        if not isinstance(projection.get("source_refs"), list) or not projection.get("source_refs"):
            errors.append("projection.source_refs must be a non-empty list")
    for key in (
        "topic_intent",
        "cadence_intent",
        "delivery_intent",
        "source_policy",
        "source_inbox",
        "briefing_status",
        "optional_integrations",
        "prompt_outline",
    ):
        if not isinstance(record.get(key), dict):
            errors.append(f"{key} must be an object")
    legacy_tooling = _has_legacy_tooling(record)
    for key in ("knowledge_store", "synthesis_tool"):
        if not isinstance(record.get(key), dict) and not legacy_tooling:
            errors.append(f"{key} must be an object")
    for key in (
        "roles",
        "skill_chain",
        "workflow_chain",
        "wrapper_actions",
        "required_runtime_capabilities",
        "optional_runtime_capabilities",
        "not_evidence_until_observed",
        "observed_evidence_required",
    ):
        if not isinstance(record.get(key), list):
            errors.append(f"{key} must be a list")
    not_evidence = set(_string_list(record.get("not_evidence_until_observed", [])))
    missing = _missing_default_evidence_guards(not_evidence)
    if missing:
        errors.append(
            "not_evidence_until_observed must include the default research evidence guard list: "
            + ", ".join(missing)
        )
    inbox = record.get("source_inbox")
    if isinstance(inbox, dict):
        errors.extend(validate_source_inbox(inbox))
    status = record.get("briefing_status")
    if isinstance(status, dict):
        errors.extend(validate_briefing_status(status))
    errors.extend(_nested_status_boundary_errors(record))
    errors.extend(_projection_boolean_boundary_errors(record))
    return errors


def validate_source_inbox(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if record.get("schema_version") != SOURCE_INBOX_SCHEMA_VERSION:
        errors.append("source_inbox.schema_version must be source_inbox/v1")
    if record.get("authority") != "projection_only":
        errors.append("source_inbox.authority must be projection_only")
    buckets = record.get("buckets")
    if not isinstance(buckets, dict):
        errors.append("source_inbox.buckets must be an object")
        return errors
    for bucket_name in ("raw_findings", "processed_notes", "briefs", "conflicts", "needs_verification"):
        bucket = buckets.get(bucket_name)
        if not isinstance(bucket, dict):
            errors.append(f"source_inbox.buckets.{bucket_name} must be an object")
            continue
        if bucket.get("status") not in OBSERVATION_STATUSES:
            errors.append(f"source_inbox.buckets.{bucket_name}.status must remain prepared or not_observed")
        if not isinstance(bucket.get("items"), list):
            errors.append(f"source_inbox.buckets.{bucket_name}.items must be a list")
    return errors


def validate_briefing_status(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if record.get("schema_version") != BRIEFING_STATUS_SCHEMA_VERSION:
        errors.append("briefing_status.schema_version must be briefing_status/v1")
    lanes = record.get("lanes")
    if not isinstance(lanes, dict):
        errors.append("briefing_status.lanes must be an object")
        return errors
    for lane_name in ("scout", "analyst", "briefer", "verification"):
        lane = lanes.get(lane_name)
        if not isinstance(lane, dict):
            errors.append(f"briefing_status.lanes.{lane_name} must be an object")
            continue
        if lane.get("status") not in OBSERVATION_STATUSES:
            errors.append(f"briefing_status.lanes.{lane_name}.status must remain prepared or not_observed")
    not_observed = set(_string_list(record.get("not_observed", [])))
    missing = _missing_default_evidence_guards(not_observed)
    if missing:
        errors.append("briefing_status.not_observed must include the default research evidence guard list: " + ", ".join(missing))
    return errors


def write_research_department_plan(paths: OmhPaths, record: dict[str, Any]) -> dict[str, Any]:
    errors = validate_research_department_plan(record)
    if errors:
        raise ValueError("; ".join(errors))
    plan_id = str(record["plan_id"])
    if research_department_plan_exists(paths, plan_id):
        raise ValueError(f"research department plan already exists: {plan_id}")
    atomic_write_json(_plan_path(paths, plan_id), record, private=True)
    _write_index_cache(paths)
    return record


def list_research_department_plans(paths: OmhPaths, *, limit: int | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for plan_path in sorted(paths.research_department_plans_dir.glob("*.json")):
        record, error = read_json_object_result(plan_path)
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


def show_research_department_plan(paths: OmhPaths, plan_id: str) -> dict[str, Any]:
    if not _valid_plan_id(plan_id):
        raise FileNotFoundError(plan_id)
    record = read_json_object(_plan_path(paths, plan_id))
    if record:
        return record
    raise FileNotFoundError(plan_id)


def summarize_research_department_plan(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "plan_id": str(record.get("plan_id", "")),
        "kind": str(record.get("kind", "")),
        "title": str(record.get("title", "")),
        "status": str(record.get("status", "")),
        "observation_status": str(record.get("observation_status", "")),
        "updated_at": str(record.get("updated_at", "")),
        "topic": str(record.get("topic_intent", {}).get("topic", "unspecified"))
        if isinstance(record.get("topic_intent"), dict)
        else "unspecified",
        "cadence": str(record.get("cadence_intent", {}).get("cadence", "unspecified"))
        if isinstance(record.get("cadence_intent"), dict)
        else "unspecified",
        "delivery_surfaces": list(record.get("delivery_intent", {}).get("surfaces", []))
        if isinstance(record.get("delivery_intent"), dict)
        else [],
        "summary": _preview(str(record.get("request_summary", "")), limit=PLAN_SUMMARY_LIMIT),
    }


def validate_research_department_store(paths: OmhPaths) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    errors: list[str] = []
    seen: set[str] = set()
    for plan_path in sorted(paths.research_department_plans_dir.glob("*.json")):
        record, error = read_json_object_result(plan_path)
        if error:
            errors.append(f"{plan_path}: {error}")
            continue
        if record:
            records.append(record)
    for record in records:
        plan_id = str(record.get("plan_id", ""))
        if plan_id in seen:
            errors.append(f"duplicate plan_id: {plan_id}")
        seen.add(plan_id)
        for error in validate_research_department_plan(record):
            errors.append(f"{plan_id or '<unknown>'}: {error}")
    index = read_json_object(paths.research_department_index_path)
    if index and index.get("schema_version") != RESEARCH_DEPARTMENT_INDEX_SCHEMA_VERSION:
        errors.append("research department index cache has unsupported schema_version")
    return {
        "schema_version": RESEARCH_DEPARTMENT_VALIDATION_SCHEMA_VERSION,
        "ok": not errors,
        "plan_count": len(records),
        "errors": errors,
        "index_authority": "cache_only",
    }


def research_department_plan_exists(paths: OmhPaths, plan_id: str) -> bool:
    return _valid_plan_id(plan_id) and _plan_path(paths, plan_id).exists()


def _role_lanes() -> list[dict[str, object]]:
    return [
        {
            "role": "scout",
            "label": "Scout",
            "status": "prepared",
            "responsibility": "Collect source candidates and raw findings without claiming retrieval until observed.",
            "primary_skills": ["web-research", "autoresearch-goal"],
            "output_bucket": "raw_findings",
        },
        {
            "role": "analyst",
            "label": "Analyst",
            "status": "prepared",
            "responsibility": "Synthesize processed notes, conflicts, confidence, and missing evidence.",
            "primary_skills": ["research-brief", "best-practice-research"],
            "output_bucket": "processed_notes",
        },
        {
            "role": "briefer",
            "label": "Briefer",
            "status": "prepared",
            "responsibility": "Prepare a digest, report, or meeting brief with unresolved gaps visible.",
            "primary_skills": ["report-package", "meeting-brief", "operating-rhythm"],
            "output_bucket": "briefs",
        },
    ]


def _workflow_chain(roles: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {
            "stage": "collect",
            "owner": "scout",
            "status": "prepared",
            "skills": _skills_for_role(roles, "scout"),
            "prepared_output": "source_inbox.raw_findings",
            "not_evidence": "source_retrieval_observed",
        },
        {
            "stage": "synthesize",
            "owner": "analyst",
            "status": "prepared",
            "skills": _skills_for_role(roles, "analyst"),
            "prepared_output": "source_inbox.processed_notes",
            "not_evidence": "synthesis_tool_query_observed",
        },
        {
            "stage": "brief",
            "owner": "briefer",
            "status": "prepared",
            "skills": _skills_for_role(roles, "briefer"),
            "prepared_output": "source_inbox.briefs",
            "not_evidence": "brief_delivered",
        },
    ]


def _skill_chain(source_policy: dict[str, object]) -> list[dict[str, str]]:
    chain = [
        {"skill": "research-department", "reason": "workflow pack owner"},
        {"skill": "web-research", "reason": "Scout lane for current/source-backed collection"},
        {"skill": "research-brief", "reason": "Analyst lane for source-backed synthesis"},
        {"skill": "report-package", "reason": "Briefer lane for digest/report output"},
        {"skill": "automation-blueprint", "reason": "cadence and delivery policy when recurring"},
    ]
    detected = set(_string_list(source_policy.get("detected_source_types", [])))
    if "papers" in detected:
        chain.append({"skill": "best-practice-research", "reason": "official/upstream or paper-backed validation"})
    if "customer" in detected:
        chain.append({"skill": "feedback-triage", "reason": "customer signal clustering before synthesis"})
    return chain


def _skills_for_role(roles: list[dict[str, object]], role_name: str) -> list[str]:
    for role in roles:
        if role.get("role") == role_name:
            return [str(item) for item in role.get("primary_skills", [])]
    return []


def _topic_intent(text: str, *, topic: str = "") -> dict[str, object]:
    explicit = topic.strip()
    inferred = ""
    if not explicit:
        match = _TOPIC_PREFIX_RE.search(text)
        if match:
            inferred = _preview(match.group(1).strip(" .,"), limit=96)
    if not explicit and not inferred:
        lowered = text.casefold()
        if any(term in lowered for term in ("competitor", "경쟁", "競合", "竞争")):
            inferred = "competitor and market signals"
        elif any(term in lowered for term in ("paper", "논문", "論文", "论文")):
            inferred = "papers and research evidence"
        elif any(term in lowered for term in ("news", "뉴스", "ニュース", "新闻")):
            inferred = "news and current source changes"
    return {
        "status": "prepared",
        "topic": explicit or inferred or "needs_confirmation",
        "explicit_topic": explicit,
        "requires_confirmation": not bool(explicit or inferred),
    }


def _cadence_intent(text: str, *, cadence: str = "") -> dict[str, object]:
    source = cadence.strip() or text
    folded = source.casefold()
    matches = [label for label, terms in _CADENCE_TERMS.items() if any(term.casefold() in folded for term in terms)]
    every = _EVERY_RE.search(source)
    selected = "unspecified"
    for candidate in ("daily", "weekday", "weekly", "monthly", "durable", "one_off"):
        if candidate in matches:
            selected = candidate
            break
    if every and selected == "unspecified":
        selected = "recurring"
    return {
        "status": "prepared",
        "cadence": selected,
        "explicit_cadence": cadence.strip(),
        "matched_terms": matches,
        "requires_confirmation": selected == "unspecified",
    }


def _delivery_intent(text: str, *, delivery: str = "") -> dict[str, object]:
    source = f"{text} {delivery}".casefold()
    surfaces = [surface for surface, terms in _DELIVERY_SURFACES.items() if any(term.casefold() in source for term in terms)]
    if not surfaces:
        surfaces = ["current-hermes-thread"]
    return {
        "status": "prepared",
        "surfaces": surfaces,
        "explicit_delivery": delivery.strip(),
        "requires_observed_gateway_evidence": any(surface not in {"current-hermes-thread", "report"} for surface in surfaces),
    }


def _knowledge_store_intent(
    text: str,
    *,
    storage: str = "",
    knowledge_store: str = "",
    obsidian: str = "unknown",
) -> dict[str, object]:
    explicit = knowledge_store.strip() or storage.strip()
    explicit_source = explicit.casefold()
    concept_source = f"{text} {explicit}".casefold()
    store_type = "local_markdown_folder"
    vendor_hint = ""
    readiness_mode = _readiness_mode(obsidian)
    if any(term in explicit_source for term in ("obsidian", "vault", "옵시디언", "볼트")):
        store_type = "obsidian_vault"
        vendor_hint = "obsidian"
    elif readiness_mode in {"available", "preferred"} and not explicit:
        store_type = "obsidian_vault"
        vendor_hint = "obsidian"
    elif any(term in concept_source for term in ("notion", "노션")):
        store_type = "notion_workspace"
        vendor_hint = "notion"
    elif any(term in concept_source for term in ("google drive", "gdrive", "google docs", "구글 드라이브")):
        store_type = "google_drive"
        vendor_hint = "google"
    elif any(term in concept_source for term in ("database", "db", "데이터베이스")):
        store_type = "database"
    elif any(term in concept_source for term in ("markdown", "md", "folder", "폴더", "마크다운")):
        store_type = "markdown_folder"
    if explicit and readiness_mode == "unknown":
        readiness_mode = "preferred"
    return {
        "schema_version": "knowledge_store_intent/v1",
        "status": "prepared",
        "type": store_type,
        "explicit_target": explicit,
        "vendor_hint": vendor_hint,
        "mode": readiness_mode,
        "readiness": _readiness_label(readiness_mode),
        "requested_capability": "persist source inboxes, notes, briefs, and unresolved verification gaps",
        "write_observed": False,
        "requires_observed_write_evidence": True,
        "boundary": "A knowledge-store preference is not write evidence or proof that the store is configured.",
    }


def _synthesis_tool_intent(
    text: str,
    *,
    synthesis_tool: str = "",
    notebooklm: str = "unknown",
) -> dict[str, object]:
    explicit = synthesis_tool.strip()
    explicit_source = explicit.casefold()
    concept_source = f"{text} {synthesis_tool}".casefold()
    tool_type = "hermes_synthesis"
    vendor_hint = ""
    readiness_mode = _readiness_mode(notebooklm)
    if any(term in explicit_source for term in ("notebooklm", "notebook lm", "notebook")):
        tool_type = "notebooklm"
        vendor_hint = "notebooklm"
    elif readiness_mode in {"available", "preferred"} and not explicit:
        tool_type = "notebooklm"
        vendor_hint = "notebooklm"
    elif any(term in concept_source for term in ("rag", "vector", "embedding", "벡터")):
        tool_type = "local_rag"
    elif any(term in concept_source for term in ("summarizer", "summary tool", "knowledge summary", "요약 도구", "요약툴")):
        tool_type = "knowledge_summarizer"
    if explicit and readiness_mode == "unknown":
        readiness_mode = "preferred"
    return {
        "schema_version": "synthesis_tool_intent/v1",
        "status": "prepared",
        "type": tool_type,
        "explicit_target": explicit,
        "vendor_hint": vendor_hint,
        "mode": readiness_mode,
        "readiness": _readiness_label(readiness_mode),
        "requested_capability": "summarize curated sources, surface conflicts, and preserve missing evidence",
        "query_observed": False,
        "workspace_observed": False,
        "boundary": "A synthesis-tool preference is not query evidence or proof that the tool is configured.",
    }


def _source_policy(text: str, *, sources: list[str]) -> dict[str, object]:
    source_text = " ".join([text, *sources])
    folded = source_text.casefold()
    detected = [label for label, terms in _SOURCE_TYPES.items() if any(term.casefold() in folded for term in terms)]
    if not detected and sources:
        detected = ["operator-supplied"]
    return {
        "status": "prepared",
        "source_boundaries": _string_list(sources),
        "detected_source_types": detected or ["needs_confirmation"],
        "paywall_policy": "flag_as_gap",
        "conflict_policy": "preserve_conflicts_until_verified",
        "freshness_policy": "state_retrieval_date_when_observed",
        "requires_confirmation": not bool(sources or detected),
    }


def _readiness_mode(mode: str) -> str:
    normalized = str(mode or "unknown").strip().lower()
    if normalized not in {"unknown", "available", "unavailable", "preferred"}:
        normalized = "unknown"
    return normalized


def _readiness_label(mode: str) -> str:
    normalized = _readiness_mode(mode)
    if normalized == "preferred":
        return "operator_prefers_if_available"
    elif normalized == "available":
        return "operator_supplied_available"
    elif normalized == "unavailable":
        return "not_available"
    return "not_checked"


def _prompt_outline(text: str, skill_chain: list[dict[str, str]]) -> dict[str, object]:
    skills = ", ".join(item["skill"] for item in skill_chain)
    subject = _preview(text, limit=160).rstrip(". ")
    return {
        "system_intent": "Hermes should prepare a research operations workflow, not claim the research has already run.",
        "operator_prompt": (
            f"Prepare a research department workflow for: {subject}. "
            f"Use skills: {skills}. Map Scout to collection, Analyst to synthesis, and Briefer to reporting. "
            "Keep collected, synthesized, briefed, delivered, and verified states separate."
        ),
        "missing_decisions": [
            "confirm topic and source boundaries",
            "confirm cadence and delivery target",
            "confirm knowledge-store destination and optional synthesis-tool readiness",
        ],
    }


def _inbox_bucket(items: list[dict[str, Any]] | None) -> dict[str, object]:
    clean_items = items or []
    return {
        "status": "not_observed" if not clean_items else "prepared",
        "items": clean_items,
    }


def _plan_path(paths: OmhPaths, plan_id: str):
    if not _valid_plan_id(plan_id):
        raise ValueError("plan_id must contain only letters, digits, and hyphens, and must not contain path separators")
    path = paths.research_department_plans_dir / f"{plan_id}.json"
    root = paths.research_department_plans_dir.resolve()
    resolved = path.resolve()
    if resolved.parent != root:
        raise ValueError("plan_id escapes research department storage")
    return path


def _write_index_cache(paths: OmhPaths) -> None:
    records = list_research_department_plans(paths)
    ensure_dir(paths.research_department_dir, private=True)
    atomic_write_json(
        paths.research_department_index_path,
        {
            "schema_version": RESEARCH_DEPARTMENT_INDEX_SCHEMA_VERSION,
            "updated_at": utc_now(),
            "authority": "cache_only",
            "plans": [summarize_research_department_plan(record) for record in records],
        },
        private=True,
    )


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
                    errors.append(f"{child_path} must not claim observed research, delivery, or integration evidence")
            errors.extend(_nested_status_boundary_errors(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_nested_status_boundary_errors(child, path=f"{path}[{index}]"))
    return errors


def _projection_boolean_boundary_errors(value: object, *, path: str = "$") -> list[str]:
    errors: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key not in {"not_observed", "not_evidence_until_observed"} and key.endswith("_observed") and bool(child):
                errors.append(f"{child_path} must remain false in projection-only research plans")
            errors.extend(_projection_boolean_boundary_errors(child, path=child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(_projection_boolean_boundary_errors(child, path=f"{path}[{index}]"))
    return errors


def _missing_default_evidence_guards(ids: set[str]) -> list[str]:
    missing: list[str] = []
    for guard in DEFAULT_NOT_EVIDENCE:
        if guard in ids:
            continue
        if any(alias in ids for alias in LEGACY_NOT_EVIDENCE_ALIASES.get(guard, ())):
            continue
        missing.append(guard)
    return missing


def _has_legacy_tooling(record: dict[str, Any]) -> bool:
    optional = record.get("optional_integrations")
    return isinstance(optional, dict) and (
        isinstance(optional.get("notebooklm"), dict) or isinstance(optional.get("obsidian"), dict)
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
    return (_SLUG_RE.sub("-", value.casefold()).strip("-") or "research-department")[:64].strip("-")


def _valid_plan_id(value: str) -> bool:
    return bool(_PLAN_ID_RE.fullmatch(str(value)))


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, tuple):
        value = list(value)
    if not isinstance(value, list):
        return [str(value).strip()] if str(value).strip() else []
    return [str(item).strip() for item in value if str(item).strip()]


def _preview(value: str, *, limit: int) -> str:
    clean = " ".join(str(value).split())
    if len(clean) <= limit:
        return clean
    return clean[: max(0, limit - 3)].rstrip() + "..."


def _default_title(text: str) -> str:
    return f"Research department: {_preview(text, limit=72)}"
