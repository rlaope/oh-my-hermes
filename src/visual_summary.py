from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .hashutil import sha256_text
from .local_store import atomic_write_json, ensure_dir, read_json_object_result, utc_now
from .paths import OmhPaths


VISUAL_PROMPT_CARD_SCHEMA_VERSION = "visual_prompt_card/v1"
VISUAL_OBSERVATION_SCHEMA_VERSION = "visual_observation/v1"
VISUAL_OBSERVATIONS_INDEX_SCHEMA_VERSION = "omh_visual_observations_index/v1"
IMAGE_GENERATION_CAPABILITY_SCHEMA_VERSION = "image_generation_capability/v1"

SOURCE_KINDS = (
    "meeting",
    "github_pr",
    "issue_feedback",
    "research_briefing",
    "report_summary",
    "release_announcement",
)
LANGUAGE_MODES = ("en", "ko", "bilingual", "source")
ASPECT_RATIOS = ("vertical_9_16", "long_scroll", "square_1_1", "portrait_4_5", "horizontal_16_9")
ASPECT_RATIO_CHOICES = ("auto",) + ASPECT_RATIOS
VISUAL_FORMATS = (
    "meeting_recap_card",
    "pr_review_infographic",
    "issue_triage_card",
    "research_briefing_board",
    "report_digest_card",
    "release_announcement_card",
)
VISUAL_FORMAT_CHOICES = ("auto",) + VISUAL_FORMATS
CAPABILITY_STATES = ("unknown", "prompt_only", "connected")
OBSERVATION_TYPES = ("generated_image_observed", "visual_qa_observed", "delivery_observed")
SUPPORTED_IMAGE_MIME_TYPES = ("image/png", "image/jpeg", "image/webp")

SAFE_VISUAL_ACTIONS = (
    "show_visual_prompt_card",
    "copy_visual_prompt",
    "revise_visual_card",
    "change_visual_language",
    "record_visual_image",
    "record_visual_qa",
    "record_visual_delivery",
    "show_visual_status",
)

_SOURCE_KIND_ALIASES = {
    "meeting": "meeting",
    "conversation": "meeting",
    "minutes": "meeting",
    "회의": "meeting",
    "회의록": "meeting",
    "github_pr": "github_pr",
    "pr": "github_pr",
    "pull_request": "github_pr",
    "review_card": "github_pr",
    "issue_feedback": "issue_feedback",
    "issue": "issue_feedback",
    "bug": "issue_feedback",
    "feedback": "issue_feedback",
    "triage": "issue_feedback",
    "이슈": "issue_feedback",
    "버그": "issue_feedback",
    "피드백": "issue_feedback",
    "research_briefing": "research_briefing",
    "research": "research_briefing",
    "news": "research_briefing",
    "competitor": "research_briefing",
    "briefing": "research_briefing",
    "리서치": "research_briefing",
    "뉴스": "research_briefing",
    "경쟁사": "research_briefing",
    "브리핑": "research_briefing",
    "report_summary": "report_summary",
    "report": "report_summary",
    "digest": "report_summary",
    "status_report": "report_summary",
    "리포트": "report_summary",
    "보고서": "report_summary",
    "release_announcement": "release_announcement",
    "release": "release_announcement",
    "announcement": "release_announcement",
    "update": "release_announcement",
    "릴리즈": "release_announcement",
    "업데이트": "release_announcement",
    "공지": "release_announcement",
}
_OBSERVATION_TYPE_ALIASES = {
    "generated-image": "generated_image_observed",
    "generated_image": "generated_image_observed",
    "generated_image_observed": "generated_image_observed",
    "image": "generated_image_observed",
    "visual-qa": "visual_qa_observed",
    "visual_qa": "visual_qa_observed",
    "visual_qa_observed": "visual_qa_observed",
    "qa": "visual_qa_observed",
    "delivery": "delivery_observed",
    "delivered": "delivery_observed",
    "delivery_observed": "delivery_observed",
}
_DEFAULT_AUDIENCE = {
    "meeting": "meeting participants",
    "github_pr": "reviewers",
    "issue_feedback": "product and engineering triage",
    "research_briefing": "operators and decision makers",
    "report_summary": "operators and stakeholders",
    "release_announcement": "users and stakeholders",
}
_HEADLINES = {
    "meeting": "Meeting Visual Summary",
    "github_pr": "PR Review Card",
    "issue_feedback": "Issue Triage Card",
    "research_briefing": "Research Briefing Card",
    "report_summary": "Report Digest Card",
    "release_announcement": "Release Announcement Card",
}
_SECTION_TEMPLATES = {
    "meeting": (
        ("summary", "Discussion focus"),
        ("decision", "Decision or open question"),
        ("action", "Next action"),
        ("risk", "Risk or missing evidence"),
    ),
    "github_pr": (
        ("summary", "What changed"),
        ("review_focus", "Review focus"),
        ("verification", "Verification status"),
        ("risk", "Risk note"),
    ),
    "issue_feedback": (
        ("signal", "User signal"),
        ("pain", "Pain point"),
        ("next_action", "Next triage step"),
        ("missing_evidence", "Missing evidence"),
    ),
    "research_briefing": (
        ("topic", "Topic"),
        ("finding", "Key finding"),
        ("implication", "Implication"),
        ("follow_up", "Follow-up"),
    ),
    "report_summary": (
        ("summary", "Executive summary"),
        ("metric", "Metric or signal"),
        ("insight", "Insight"),
        ("next_action", "Next action"),
    ),
    "release_announcement": (
        ("summary", "What is new"),
        ("benefit", "Who benefits"),
        ("migration", "Migration note"),
        ("call_to_action", "Next action"),
    ),
}
_MISSING_INPUTS = {
    "meeting": ("explicit decisions", "action owners", "risks or open questions"),
    "github_pr": ("changed scope", "review focus", "verification evidence", "risk notes"),
    "issue_feedback": ("source boundary", "severity", "suspected area", "next owner"),
    "research_briefing": ("source list", "freshness", "confidence", "follow-up decision"),
    "report_summary": ("report period", "source data", "metric definitions", "decision owner"),
    "release_announcement": ("audience", "new capabilities", "migration notes", "call to action"),
}
_FORMAT_BY_KIND = {
    "meeting": "meeting_recap_card",
    "github_pr": "pr_review_infographic",
    "issue_feedback": "issue_triage_card",
    "research_briefing": "research_briefing_board",
    "report_summary": "report_digest_card",
    "release_announcement": "release_announcement_card",
}
_FORMAT_PROFILES = {
    "meeting_recap_card": {
        "label": "meeting recap visual card",
        "layout_type": "meeting_recap_card",
        "default_aspect_ratio": "vertical_9_16",
        "structure": ("Context", "Decisions", "Owners", "Risks", "Next actions"),
        "theme_direction": "collaboration room, agenda board, speaker notes, calm operator palette",
        "visual_metaphor": "meeting table, agenda cards, decision stamps, action-owner markers",
    },
    "pr_review_infographic": {
        "label": "PR review infographic",
        "layout_type": "pr_review_infographic",
        "default_aspect_ratio": "square_1_1",
        "structure": ("Summary", "Changed files or surface", "Review focus", "Validation", "Risk", "Conclusion"),
        "theme_direction": "developer workspace, code review panels, test status, precise technical lines",
        "visual_metaphor": "code panels, merge arrows, review checkmarks, CI badges",
    },
    "issue_triage_card": {
        "label": "issue triage visual card",
        "layout_type": "issue_triage_card",
        "default_aspect_ratio": "vertical_9_16",
        "structure": ("Signal", "Impact", "Suspected area", "Next investigation", "Missing evidence"),
        "theme_direction": "incident desk, alert markers, priority tags, product support board",
        "visual_metaphor": "ticket cards, warning triangle, severity ladder, reproduction path",
    },
    "research_briefing_board": {
        "label": "research briefing board",
        "layout_type": "research_briefing_board",
        "default_aspect_ratio": "long_scroll",
        "structure": ("Topic", "Findings", "Sources", "Contradictions", "Implications", "Next scan"),
        "theme_direction": "research wall, source snippets, synthesis map, calm analytical grid",
        "visual_metaphor": "source inbox, evidence pins, synthesis nodes, briefing memo",
    },
    "report_digest_card": {
        "label": "report digest card",
        "layout_type": "report_digest_card",
        "default_aspect_ratio": "long_scroll",
        "structure": ("Executive summary", "Metrics", "Trend", "Insight", "Decision", "Follow-up"),
        "theme_direction": "report dashboard, metric cards, ledger lines, board-ready briefing",
        "visual_metaphor": "charts, tables, KPI strips, executive memo sections",
    },
    "release_announcement_card": {
        "label": "release announcement card",
        "layout_type": "release_announcement_card",
        "default_aspect_ratio": "square_1_1",
        "structure": ("What is new", "Why it matters", "Who benefits", "Migration note", "Call to action"),
        "theme_direction": "launch board, product update layers, clean announcement energy",
        "visual_metaphor": "stacked product cards, sparkle markers, release ribbon, update badge",
    },
}
_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}
_SLUG_RE = re.compile(r"[^a-z0-9]+")
_VISUAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,180}$")


def new_visual_card_id(
    kind: str,
    *,
    payload: dict[str, Any] | None = None,
    now: datetime | str | None = None,
) -> str:
    basis = payload or {"source_kind": normalize_source_kind(kind), "created_at": _stamp(now) if now else "deterministic"}
    digest = sha256_text(_stable_json(basis))[:12]
    return f"{_slugify(normalize_source_kind(kind))}-{digest}"


def normalize_source_kind(kind: str) -> str:
    value = str(kind).strip().lower()
    canonical = _SOURCE_KIND_ALIASES.get(value)
    if canonical is None:
        raise ValueError(f"unsupported visual source kind: {kind}; expected one of {', '.join(SOURCE_KINDS)}")
    return canonical


def parse_section_arg(value: str) -> dict[str, str]:
    parts = str(value).split(":")
    if len(parts) != 3 or not all(part.strip() for part in parts):
        raise ValueError("--section must use role:title:text with exactly three colon-separated fields")
    role, title, text = (part.strip() for part in parts)
    return {"role": role, "title": title, "image_text": text}


def build_visual_prompt_card(
    *,
    kind: str,
    headline: str = "",
    audience: str = "",
    language: str = "source",
    aspect_ratio: str = "auto",
    visual_format: str = "auto",
    sections: list[dict[str, str]] | None = None,
    source_text: str = "",
    capability_state: str = "unknown",
    card_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    source_kind = normalize_source_kind(kind)
    if language not in LANGUAGE_MODES:
        raise ValueError(f"unsupported visual language: {language}; expected one of {', '.join(LANGUAGE_MODES)}")
    resolved_format = resolve_visual_format(source_kind, visual_format)
    format_profile = _FORMAT_PROFILES[resolved_format]
    resolved_aspect_ratio = resolve_aspect_ratio(aspect_ratio, resolved_format)
    if capability_state not in CAPABILITY_STATES:
        raise ValueError(f"unsupported visual capability state: {capability_state}; expected one of {', '.join(CAPABILITY_STATES)}")

    source_excerpt = _source_excerpt(source_text)
    structured_sections = [_normalize_section(item, index) for index, item in enumerate(sections or [], start=1)]
    if structured_sections:
        copy_mode = "structured"
        requires_review = False
        missing_inputs: list[str] = []
        visual_sections = structured_sections
    elif source_excerpt:
        copy_mode = "extractive_draft"
        requires_review = True
        missing_inputs = list(_MISSING_INPUTS[source_kind])
        visual_sections = _extractive_sections(source_kind, source_excerpt)
    else:
        raise ValueError("provide at least one --section, positional source text, or --from-file input")

    resolved_headline = str(headline).strip() or _HEADLINES[source_kind]
    record = {
        "schema_version": VISUAL_PROMPT_CARD_SCHEMA_VERSION,
        "card_id": "",
        "status": "prepared",
        "copy_mode": copy_mode,
        "requires_human_or_hermes_review": requires_review,
        "missing_structured_inputs": missing_inputs,
        "source_kind": source_kind,
        "audience": str(audience).strip() or _DEFAULT_AUDIENCE[source_kind],
        "languages": _languages(language),
        "aspect_ratio": resolved_aspect_ratio,
        "visual_format": resolved_format,
        "layout": {
            "type": format_profile["layout_type"],
            "sections": [section["role"] for section in visual_sections],
            "hierarchy": ", ".join(format_profile["structure"]),
            "recommended_aspect_ratio": format_profile["default_aspect_ratio"],
        },
        "format_profile": {
            "label": format_profile["label"],
            "structure": list(format_profile["structure"]),
            "theme_direction": format_profile["theme_direction"],
            "visual_metaphor": format_profile["visual_metaphor"],
        },
        "sections": visual_sections,
        "image_text": {
            "headline": _clip_words(resolved_headline, 12),
            "footer": "Prepared by Hermes with OMH",
        },
        "style_direction": {
            "mood": str(format_profile["theme_direction"]),
            "typography": "readable labels, short lines, and enough canvas height for the selected format",
            "palette": "controlled by wrapper or user preference",
        },
        "generation_prompt": _generation_prompt(
            source_kind,
            resolved_headline,
            visual_sections,
            language,
            resolved_aspect_ratio,
            resolved_format,
        ),
        "negative_prompt": (
            "Do not invent facts, owners, decisions, test results, approvals, or delivery claims. "
            "Do not render tiny unreadable paragraphs. Do not hide source uncertainty. "
            "Do not add logos or platform marks unless the user supplied them."
        ),
        "quality_checks": _quality_checks(),
        "capability_detection": {
            "schema_version": IMAGE_GENERATION_CAPABILITY_SCHEMA_VERSION,
            "state": capability_state,
            "meaning": "Wrapper-reported generator availability only; not generation evidence.",
        },
        "available_actions": visual_wrapper_actions(capability_state),
        "source_excerpt": source_excerpt,
        "not_evidence_until_observed": [
            "image_generated",
            "visual_qa_passed",
            "delivered",
        ],
    }
    if created_at is not None:
        record["created_at"] = created_at
    record["card_id"] = card_id or new_visual_card_id(source_kind, payload=_visual_card_identity_payload(record))
    errors = validate_visual_prompt_card(record)
    if errors:
        raise ValueError("; ".join(errors))
    return record


def resolve_visual_format(source_kind: str, visual_format: str = "auto") -> str:
    if visual_format not in VISUAL_FORMAT_CHOICES:
        raise ValueError(f"unsupported visual format: {visual_format}; expected one of {', '.join(VISUAL_FORMAT_CHOICES)}")
    if visual_format == "auto":
        return _FORMAT_BY_KIND[normalize_source_kind(source_kind)]
    return visual_format


def resolve_aspect_ratio(aspect_ratio: str, visual_format: str) -> str:
    if aspect_ratio not in ASPECT_RATIO_CHOICES:
        raise ValueError(f"unsupported visual aspect ratio: {aspect_ratio}; expected one of {', '.join(ASPECT_RATIO_CHOICES)}")
    if aspect_ratio == "auto":
        return str(_FORMAT_PROFILES[visual_format]["default_aspect_ratio"])
    return aspect_ratio


def validate_visual_prompt_card(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if record.get("schema_version") != VISUAL_PROMPT_CARD_SCHEMA_VERSION:
        errors.append("schema_version must be visual_prompt_card/v1")
    if not _valid_visual_id(str(record.get("card_id", ""))):
        errors.append("card_id must contain only letters, digits, and hyphens, and must not contain path separators")
    if record.get("status") != "prepared":
        errors.append("status must be prepared")
    if record.get("copy_mode") not in {"structured", "extractive_draft"}:
        errors.append("copy_mode must be structured or extractive_draft")
    source_kind = str(record.get("source_kind", ""))
    if source_kind not in SOURCE_KINDS:
        errors.append(f"source_kind must be one of {', '.join(SOURCE_KINDS)}")
    if record.get("aspect_ratio") not in ASPECT_RATIOS:
        errors.append(f"aspect_ratio must be one of {', '.join(ASPECT_RATIOS)}")
    if not isinstance(record.get("languages"), list) or not record.get("languages"):
        errors.append("languages must be a non-empty list")
    if not isinstance(record.get("sections"), list) or not record.get("sections"):
        errors.append("sections must be a non-empty list")
    else:
        for index, section in enumerate(record["sections"], start=1):
            if not isinstance(section, dict):
                errors.append(f"sections[{index}] must be an object")
                continue
            if not str(section.get("role", "")).strip():
                errors.append(f"sections[{index}].role is required")
            if not str(section.get("title", "")).strip():
                errors.append(f"sections[{index}].title is required")
            if not str(section.get("image_text", "")).strip():
                errors.append(f"sections[{index}].image_text is required")
            if section.get("priority") not in {"primary", "secondary", "supporting"}:
                errors.append(f"sections[{index}].priority must be primary, secondary, or supporting")
            if int(section.get("max_words", 0) or 0) < 4:
                errors.append(f"sections[{index}].max_words must be at least 4")
    if record.get("visual_format") not in VISUAL_FORMATS:
        errors.append(f"visual_format must be one of {', '.join(VISUAL_FORMATS)}")
    layout = record.get("layout", {})
    allowed_layout_types = {str(profile["layout_type"]) for profile in _FORMAT_PROFILES.values()}
    if not isinstance(layout, dict) or layout.get("type") not in allowed_layout_types:
        errors.append(f"layout.type must be one of {', '.join(sorted(allowed_layout_types))}")
    profile = record.get("format_profile", {})
    if not isinstance(profile, dict) or not str(profile.get("theme_direction", "")).strip():
        errors.append("format_profile.theme_direction is required")
    image_text = record.get("image_text", {})
    if not isinstance(image_text, dict) or not str(image_text.get("headline", "")).strip():
        errors.append("image_text.headline is required")
    capability = record.get("capability_detection", {})
    if not isinstance(capability, dict) or capability.get("schema_version") != IMAGE_GENERATION_CAPABILITY_SCHEMA_VERSION:
        errors.append("capability_detection.schema_version must be image_generation_capability/v1")
    elif capability.get("state") not in CAPABILITY_STATES:
        errors.append(f"capability_detection.state must be one of {', '.join(CAPABILITY_STATES)}")
    if not isinstance(record.get("quality_checks"), list) or not record.get("quality_checks"):
        errors.append("quality_checks must be a non-empty list")
    if not isinstance(record.get("not_evidence_until_observed"), list):
        errors.append("not_evidence_until_observed must be a list")
    return errors


def visual_wrapper_actions(capability_state: str = "unknown") -> list[str]:
    if capability_state not in CAPABILITY_STATES:
        raise ValueError(f"unsupported visual capability state: {capability_state}")
    actions = list(SAFE_VISUAL_ACTIONS)
    if capability_state == "connected":
        actions.insert(4, "generate_visual_image")
    return actions


def normalize_observation_type(value: str) -> str:
    normalized = str(value).strip().lower()
    canonical = _OBSERVATION_TYPE_ALIASES.get(normalized)
    if canonical is None:
        raise ValueError(f"unsupported visual observation type: {value}; expected one of {', '.join(OBSERVATION_TYPES)}")
    return canonical


def build_visual_observation(
    *,
    card_id: str,
    observation_type: str,
    path_or_uri: str,
    evidence_summary: str,
    mime_type: str = "",
    observer: str = "wrapper_or_user",
    observed_at: str | None = None,
    observation_id: str | None = None,
) -> dict[str, Any]:
    canonical_type = normalize_observation_type(observation_type)
    record = {
        "schema_version": VISUAL_OBSERVATION_SCHEMA_VERSION,
        "observation_id": observation_id or new_visual_observation_id(card_id, canonical_type, observed_at),
        "visual_card_id": str(card_id).strip(),
        "observation_type": canonical_type,
        "status": "observed",
        "observed_at": observed_at or utc_now(),
        "observer": str(observer).strip() or "wrapper_or_user",
        "artifact": {
            "kind": "image",
            "path_or_uri": str(path_or_uri).strip(),
            "mime_type": _mime_type(path_or_uri, mime_type),
        },
        "evidence_summary": str(evidence_summary).strip(),
        "does_not_prove": _does_not_prove(canonical_type),
    }
    errors = validate_visual_observation(record)
    if errors:
        raise ValueError("; ".join(errors))
    return record


def new_visual_observation_id(card_id: str, observation_type: str, now: datetime | str | None = None) -> str:
    if not _valid_visual_id(str(card_id)):
        raise ValueError("visual card id must contain only letters, digits, and hyphens")
    return f"{_stamp(now)}-{_slugify(card_id)}-{_slugify(normalize_observation_type(observation_type))}-{secrets.token_hex(3)}"


def validate_visual_observation(record: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if record.get("schema_version") != VISUAL_OBSERVATION_SCHEMA_VERSION:
        errors.append("schema_version must be visual_observation/v1")
    if not _valid_visual_id(str(record.get("observation_id", ""))):
        errors.append("observation_id must contain only letters, digits, and hyphens, and must not contain path separators")
    if not _valid_visual_id(str(record.get("visual_card_id", ""))):
        errors.append("visual_card_id must contain only letters, digits, and hyphens, and must not contain path separators")
    if record.get("observation_type") not in OBSERVATION_TYPES:
        errors.append(f"observation_type must be one of {', '.join(OBSERVATION_TYPES)}")
    if record.get("status") != "observed":
        errors.append("status must be observed")
    if not str(record.get("observer", "")).strip():
        errors.append("observer is required")
    if not str(record.get("evidence_summary", "")).strip():
        errors.append("evidence_summary is required")
    artifact = record.get("artifact", {})
    if not isinstance(artifact, dict):
        errors.append("artifact must be an object")
    else:
        path_or_uri = str(artifact.get("path_or_uri", "")).strip()
        if not _valid_path_or_uri(path_or_uri):
            errors.append("artifact.path_or_uri must be an absolute local path or URI")
        if artifact.get("kind") != "image":
            errors.append("artifact.kind must be image")
        if artifact.get("mime_type") not in SUPPORTED_IMAGE_MIME_TYPES:
            errors.append(f"artifact.mime_type must be one of {', '.join(SUPPORTED_IMAGE_MIME_TYPES)}")
    if not isinstance(record.get("does_not_prove"), list):
        errors.append("does_not_prove must be a list")
    return errors


def write_visual_observation(paths: OmhPaths, record: dict[str, Any]) -> dict[str, Any]:
    errors = validate_visual_observation(record)
    if errors:
        raise ValueError("; ".join(errors))
    observation_id = str(record["observation_id"])
    path = _observation_path(paths, observation_id)
    if path.exists():
        raise ValueError(f"visual observation already exists: {observation_id}")
    atomic_write_json(path, record, private=True)
    _write_observations_index(paths)
    return record


def list_visual_observations(paths: OmhPaths, *, card_id: str | None = None) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for observation_path in sorted(paths.visual_observations_dir.glob("*.json")):
        if observation_path.name == "index.json":
            continue
        record, error = read_json_object_result(observation_path)
        if error or not record:
            continue
        if card_id and record.get("visual_card_id") != card_id:
            continue
        records.append(record)
    records.sort(key=lambda item: str(item.get("observed_at", "")))
    return records


def summarize_visual_observation(record: dict[str, Any]) -> dict[str, str]:
    artifact = record.get("artifact", {}) if isinstance(record.get("artifact"), dict) else {}
    return {
        "observation_id": str(record.get("observation_id", "")),
        "visual_card_id": str(record.get("visual_card_id", "")),
        "observation_type": str(record.get("observation_type", "")),
        "status": str(record.get("status", "")),
        "observed_at": str(record.get("observed_at", "")),
        "artifact": str(artifact.get("path_or_uri", "")),
        "mime_type": str(artifact.get("mime_type", "")),
    }


def _normalize_section(item: dict[str, str], index: int) -> dict[str, Any]:
    role = str(item.get("role", "")).strip()
    title = str(item.get("title", "")).strip()
    text = _clip_words(str(item.get("image_text", "")).strip(), 18)
    if not role or not title or not text:
        raise ValueError("section role, title, and text are required")
    return {
        "role": _slugify(role),
        "title": _clip_words(title, 8),
        "image_text": text,
        "priority": "primary" if index == 1 else ("secondary" if index <= 3 else "supporting"),
        "max_words": 18,
    }


def _extractive_sections(kind: str, source_excerpt: str) -> list[dict[str, Any]]:
    snippets = _source_snippets(source_excerpt)
    sections: list[dict[str, Any]] = []
    for index, (role, title) in enumerate(_SECTION_TEMPLATES[kind], start=1):
        text = snippets[index - 1] if index <= len(snippets) else f"Needs review: provide {title.lower()}."
        sections.append(
            {
                "role": role,
                "title": title,
                "image_text": _clip_words(text, 18),
                "priority": "primary" if index == 1 else ("secondary" if index <= 3 else "supporting"),
                "max_words": 18,
            }
        )
    return sections


def _source_snippets(source_excerpt: str) -> list[str]:
    lines = [line.strip(" -\t") for line in source_excerpt.splitlines() if line.strip(" -\t")]
    if len(lines) < 2:
        sentences = re.split(r"(?<=[.!?])\s+", source_excerpt)
        lines.extend(sentence.strip() for sentence in sentences if sentence.strip())
    seen: set[str] = set()
    snippets: list[str] = []
    for line in lines:
        text = _clip_words(" ".join(line.split()), 18)
        if text and text not in seen:
            snippets.append(text)
            seen.add(text)
        if len(snippets) >= 4:
            break
    return snippets or ["Needs review: provide source details."]


def _source_excerpt(source_text: str, *, limit: int = 1200) -> str:
    text = str(source_text or "").strip()
    if not text:
        return ""
    normalized = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _visual_card_identity_payload(record: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "schema_version",
        "status",
        "copy_mode",
        "requires_human_or_hermes_review",
        "missing_structured_inputs",
        "source_kind",
        "audience",
        "languages",
        "aspect_ratio",
        "visual_format",
        "layout",
        "format_profile",
        "sections",
        "image_text",
        "style_direction",
        "generation_prompt",
        "negative_prompt",
        "quality_checks",
        "capability_detection",
        "source_excerpt",
        "not_evidence_until_observed",
    )
    return {key: record[key] for key in keys if key in record}


def _stable_json(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _languages(language: str) -> list[str]:
    if language == "bilingual":
        return ["en", "ko"]
    return [language]


def _generation_prompt(
    kind: str,
    headline: str,
    sections: list[dict[str, Any]],
    language: str,
    aspect_ratio: str,
    visual_format: str,
) -> str:
    section_lines = "\n".join(
        f"- {section['title']}: {section['image_text']}"
        for section in sections
    )
    profile = _FORMAT_PROFILES[visual_format]
    return (
        f"Create a {aspect_ratio} {profile['label']} for {kind}. "
        f"Use language mode {language}. Headline: {headline}. "
        f"Use this theme direction: {profile['theme_direction']}. "
        f"Use this visual metaphor: {profile['visual_metaphor']}. "
        f"Common structure: {', '.join(profile['structure'])}. "
        f"{_aspect_guidance(aspect_ratio)} "
        "Keep visible text short, readable, and faithful to the supplied copy. "
        "Do not force every source kind into the same grid; adapt composition to the format.\n"
        f"Card copy:\n{section_lines}"
    )


def _aspect_guidance(aspect_ratio: str) -> str:
    if aspect_ratio == "long_scroll":
        return "Use a long vertical document-style canvas; let the card extend downward when content needs more sections."
    if aspect_ratio == "portrait_4_5":
        return "Use a portrait social-card canvas with compact but readable sections."
    if aspect_ratio == "square_1_1":
        return "Use a square PR/social infographic canvas with a tight three-part reading path."
    if aspect_ratio == "horizontal_16_9":
        return "Use a horizontal briefing-slide canvas with left-to-right information flow."
    return "Use a vertical mobile-friendly canvas with clear section rhythm."


def _quality_checks() -> list[dict[str, str]]:
    return [
        {
            "name": "text_readable",
            "required_evidence": "visual_qa_observed",
            "boundary": "prompt guidance is not visual QA evidence",
        },
        {
            "name": "facts_match_source",
            "required_evidence": "human_or_wrapper_review",
            "boundary": "extractive draft copy still requires review before public use",
        },
        {
            "name": "delivery_confirmed",
            "required_evidence": "delivery_observed",
            "boundary": "generated image evidence is not delivery evidence",
        },
    ]


def _mime_type(path_or_uri: str, mime_type: str) -> str:
    supplied = str(mime_type).strip().lower()
    if supplied:
        return supplied
    suffix = Path(urlparse(str(path_or_uri)).path).suffix.lower()
    return _MIME_BY_SUFFIX.get(suffix, "")


def _does_not_prove(observation_type: str) -> list[str]:
    if observation_type == "generated_image_observed":
        return ["visual_qa_passed", "delivered"]
    if observation_type == "visual_qa_observed":
        return ["delivered"]
    return ["visual_qa_passed"] if observation_type == "delivery_observed" else []


def _observation_path(paths: OmhPaths, observation_id: str) -> Path:
    if not _valid_visual_id(observation_id):
        raise ValueError("visual observation id must contain only letters, digits, and hyphens")
    path = paths.visual_observations_dir / f"{observation_id}.json"
    root = paths.visual_observations_dir.resolve()
    resolved = path.resolve()
    if resolved.parent != root:
        raise ValueError("observation_id escapes visual observation storage")
    return path


def _write_observations_index(paths: OmhPaths) -> None:
    records = list_visual_observations(paths)
    ensure_dir(paths.visual_observations_dir, private=True)
    atomic_write_json(
        paths.visual_observations_index_path,
        {
            "schema_version": VISUAL_OBSERVATIONS_INDEX_SCHEMA_VERSION,
            "updated_at": utc_now(),
            "authority": "cache_only",
            "observations": [summarize_visual_observation(record) for record in records],
        },
        private=True,
    )


def _valid_path_or_uri(value: str) -> bool:
    if not value or "\x00" in value:
        return False
    parsed = urlparse(value)
    if parsed.scheme:
        if parsed.scheme == "file":
            return Path(parsed.path).is_absolute()
        return bool(parsed.netloc)
    path = Path(value).expanduser()
    return path.is_absolute()


def _valid_visual_id(value: str) -> bool:
    return bool(_VISUAL_ID_RE.match(value)) and "/" not in value and "\\" not in value and ".." not in value


def _clip_words(value: str, max_words: int) -> str:
    words = str(value).split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(" ,;:") + "..."


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
    return (_SLUG_RE.sub("-", str(value).lower()).strip("-") or "visual")[:64].strip("-")
