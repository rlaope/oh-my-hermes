from __future__ import annotations

from typing import Final, NotRequired, TypedDict

from ..runtime.claims import (
    DEFAULT_RUNTIME_CLAIM_BOUNDARY as DEFAULT_CLAIM_BOUNDARY,
    RUNTIME_CLAIM_BLOCK_REASONS as CLAIM_BLOCK_REASONS,
    RUNTIME_CLAIM_LABELS as CLAIM_LABELS,
    RUNTIME_CLAIM_LADDER as CLAIM_LADDER,
    RUNTIME_VALIDATION_BLOCK_REASON,
    Claim,
    JsonValue,
    RuntimeBlockedClaim,
)


SCHEMA_VERSION: Final = "omh_conformance_report/v1"
RUNTIME_SUBJECT_TYPE: Final = "runtime_run"


class Subject(TypedDict):
    type: str
    id: str


BlockedClaim = RuntimeBlockedClaim


class EvidenceItem(TypedDict):
    kind: str
    status: str
    source: str


class ConformanceReport(TypedDict):
    schema_version: str
    ok: bool
    subject: Subject
    claim_state: str
    allowed_claims: list[str]
    blocked_claims: list[BlockedClaim]
    evidence: list[EvidenceItem]
    violations: list[str]
    claim_boundary: str
    next_action: NotRequired[str]
    safe_summary: NotRequired[str]
