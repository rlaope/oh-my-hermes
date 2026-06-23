from __future__ import annotations

import hashlib
import re
from typing import Any


CONTEXT_ARTIFACT_REF_SCHEMA_VERSION = "omh_context_artifact_ref/v1"
MAX_VISIBLE_MESSAGE_CHARS = 180
MAX_SUMMARY_CHARS = 240
MAX_SOURCE_REF_CHARS = 240
MAX_EVIDENCE_REFS = 8
MAX_EVIDENCE_REF_CHARS = 160


def compact_visible_text(value: Any, *, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text:
        return ""
    if len(text) <= max_chars:
        return text
    if max_chars <= 3:
        return text[:max_chars]
    return f"{text[: max_chars - 3]}..."


def compact_context_refs(
    values: Any,
    *,
    max_items: int = MAX_EVIDENCE_REFS,
    max_chars: int = MAX_EVIDENCE_REF_CHARS,
) -> tuple[list[str], int]:
    if not isinstance(values, (list, tuple)):
        return [], 0
    seen: list[str] = []
    omitted = 0
    for value in values:
        text = compact_visible_text(value, max_chars=max_chars)
        if not text:
            continue
        if text in seen:
            continue
        if len(seen) >= max_items:
            omitted += 1
            continue
        seen.append(text)
    return seen, omitted


def context_budget_payload() -> dict[str, object]:
    return {
        "schema_version": "omh_context_budget/v1",
        "max_visible_message_chars": MAX_VISIBLE_MESSAGE_CHARS,
        "max_summary_chars": MAX_SUMMARY_CHARS,
        "max_evidence_refs": MAX_EVIDENCE_REFS,
        "max_evidence_ref_chars": MAX_EVIDENCE_REF_CHARS,
        "raw_output_policy": "store_raw_output_as_artifact_and_inject_refs_and_summary_only",
    }


def raw_output_artifact_ref(
    text: str,
    *,
    source: str,
    evidence_refs: list[str] | tuple[str, ...] | None = None,
    omitted_evidence_ref_count: int = 0,
) -> dict[str, object]:
    compact_refs, extra_omitted = compact_context_refs(evidence_refs or [])
    encoded = text.encode("utf-8")
    return {
        "schema_version": CONTEXT_ARTIFACT_REF_SCHEMA_VERSION,
        "source": compact_visible_text(source or "stdin", max_chars=MAX_SOURCE_REF_CHARS),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "byte_count": len(encoded),
        "line_count": len(text.splitlines()),
        "evidence_refs": compact_refs,
        "omitted_evidence_ref_count": omitted_evidence_ref_count + extra_omitted,
        "storage_policy": "store_raw_output_as_artifact",
        "in_context_policy": "refs_and_summary_only",
        "raw_content_included": False,
        "claim_boundary": "Raw output should stay in artifacts; Hermes context receives only this reference and bounded summaries.",
    }
