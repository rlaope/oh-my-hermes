"""Append-only explicit-path persistence for paired-run decisions."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Final

from ..system.descriptor_lock import (
    DescriptorLockError,
    locked_descriptor,
    require_descriptor_lock_backend,
)
from ..system.secure_regular_file import (
    SecureFileError,
    append_bytes,
    open_regular_read,
    open_regular_update,
    read_bounded,
    validate_no_symlinks,
)
from .paired_run_provenance import receipt_provenance_errors
from .paired_run_validation import _parse_structural_paired_run_decision
from .paired_run_model import (
    ArmSpec,
    BehaviorVerdict,
    DECISION_SCHEMA_V1,
    InfrastructureStatus,
    PairedRunDecision,
    PairedRunValidationError,
    RecordedResult,
    TaskSpec,
)

_MAX_STORE_BYTES: Final = 8 * 1_024 * 1_024


class PairedRunStoreError(Exception):
    __slots__ = ("reason",)

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def append_paired_run_decision(
    path: Path,
    decision: PairedRunDecision,
    omh_home: Path,
) -> None:
    """Validate prior arrival state and append under one OS file lock."""
    candidate = _parse_candidate(decision)
    _require_receipts(candidate, omh_home)
    try:
        require_descriptor_lock_backend()
        validate_no_symlinks(path)
        with open_regular_update(path, private=True) as descriptor, locked_descriptor(
            descriptor,
            path,
        ):
            existing = read_bounded(descriptor, _MAX_STORE_BYTES)
            records = _parse_records(path, existing, omh_home)
            if any(item.decision_id == candidate.decision_id for item in records):
                raise PairedRunStoreError("candidate decision_id must be unique")
            predecessor_ref = candidate.supersedes_decision_ref
            if predecessor_ref is None:
                if any(_pair_identity(item) == _pair_identity(candidate) for item in records):
                    raise PairedRunStoreError("an existing pair must be superseded explicitly")
            else:
                predecessor = next(
                    (item for item in records if item.decision_id == predecessor_ref),
                    None,
                )
                if predecessor is None:
                    raise PairedRunStoreError("supersedes_decision_ref must name an earlier decision")
                if any(item.supersedes_decision_ref == predecessor_ref for item in records):
                    raise PairedRunStoreError("supersede chain must not fork")
                _validate_transition(predecessor, candidate)
            payload = json.dumps(candidate.to_record(), sort_keys=True).encode("utf-8") + b"\n"
            if existing and not existing.endswith(b"\n"):
                payload = b"\n" + payload
            if len(existing) + len(payload) > _MAX_STORE_BYTES:
                raise PairedRunStoreError("paired-run store append exceeds the byte limit")
            os.lseek(descriptor, 0, os.SEEK_END)
            append_bytes(descriptor, payload)
    except (DescriptorLockError, OSError, SecureFileError) as exc:
        raise PairedRunStoreError("paired-run store path is unsafe or unreadable") from exc


def latest_paired_run_decision(
    path: Path,
    decision_id: str,
    omh_home: Path,
) -> PairedRunDecision:
    """Return the latest arrival in the chain rooted at ``decision_id``."""
    try:
        require_descriptor_lock_backend()
        validate_no_symlinks(path)
        with open_regular_read(path) as descriptor, locked_descriptor(descriptor, path):
            records = _parse_records(
                path,
                read_bounded(descriptor, _MAX_STORE_BYTES),
                omh_home,
            )
    except (DescriptorLockError, OSError, SecureFileError) as exc:
        raise PairedRunStoreError("paired-run store path is unsafe or unreadable") from exc
    current = next((item for item in records if item.decision_id == decision_id), None)
    if current is None:
        raise PairedRunStoreError("decision_id was not found")
    visited: set[str] = set()
    while current.decision_id not in visited:
        visited.add(current.decision_id)
        successors = [item for item in records if item.supersedes_decision_ref == current.decision_id]
        if not successors:
            return current
        if len(successors) != 1:
            raise PairedRunStoreError("supersede chain must not fork")
        current = successors[0]
    raise PairedRunStoreError("supersede chain must not cycle")


def _parse_candidate(decision: PairedRunDecision) -> PairedRunDecision:
    try:
        return _parse_structural_paired_run_decision(decision.to_json())
    except PairedRunValidationError as exc:
        raise PairedRunStoreError(f"candidate decision is invalid: {exc}") from exc


def _parse_records(path: Path, content: bytes, omh_home: Path) -> list[PairedRunDecision]:
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeError as exc:
        raise PairedRunStoreError("paired-run store contains malformed lines") from exc
    records: list[PairedRunDecision] = []
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            records.append(_parse_structural_paired_run_decision(line))
        except PairedRunValidationError as exc:
            raise PairedRunStoreError(
                f"paired-run store contains an invalid record at {path}:{index}: {exc}"
            ) from exc
    _validate_graph(records)
    for record in records:
        _require_receipts(record, omh_home)
    return records


def _validate_graph(records: list[PairedRunDecision]) -> None:
    seen: dict[str, PairedRunDecision] = {}
    successors: dict[str, str] = {}
    for record in records:
        if record.decision_id in seen:
            raise PairedRunStoreError("decision_id values must be unique")
        predecessor_ref = record.supersedes_decision_ref
        if predecessor_ref is not None:
            if predecessor_ref == record.decision_id:
                raise PairedRunStoreError("supersede chain must not self-link")
            predecessor = seen.get(predecessor_ref)
            if predecessor is None:
                raise PairedRunStoreError("supersedes_decision_ref must name an earlier decision")
            if predecessor_ref in successors:
                raise PairedRunStoreError("supersede chain must not fork")
            _validate_transition(predecessor, record)
            successors[predecessor_ref] = record.decision_id
        seen[record.decision_id] = record


def _require_receipts(decision: PairedRunDecision, omh_home: Path) -> None:
    if errors := receipt_provenance_errors(decision, omh_home):
        raise PairedRunStoreError(errors[0])


def _pair_identity(
    decision: PairedRunDecision,
) -> tuple[ArmSpec, ArmSpec, tuple[TaskSpec, ...], str, int, int, str]:
    return (
        decision.baseline,
        decision.variant,
        decision.tasks,
        decision.task_set_digest,
        decision.max_total_runs,
        decision.max_dispatch_seconds,
        decision.execution_revision,
    )


def _validate_transition(prior: PairedRunDecision, candidate: PairedRunDecision) -> None:
    if _pair_identity(prior) != _pair_identity(candidate):
        raise PairedRunStoreError("superseding decisions must preserve pair identity")
    # v1 history may be superseded by v2, which adds timing; a v2 decision is
    # never superseded by v1, which would silently drop it.
    if (
        prior.schema_version != DECISION_SCHEMA_V1
        and candidate.schema_version == DECISION_SCHEMA_V1
    ):
        raise PairedRunStoreError("superseding decisions must not downgrade the schema version")
    prior_rows = {(item.task_id, item.arm): item for item in prior.results}
    candidate_rows = {(item.task_id, item.arm): item for item in candidate.results}
    for key, prior_row in prior_rows.items():
        _validate_row_transition(prior_row, candidate_rows[key])


def _validate_row_transition(prior: RecordedResult, candidate: RecordedResult) -> None:
    if prior.infrastructure_status is InfrastructureStatus.OBSERVED:
        unchanged = (
            candidate.infrastructure_status is InfrastructureStatus.OBSERVED
            and candidate.behavior_verdict is prior.behavior_verdict
            and candidate.receipt_ref == prior.receipt_ref
            and candidate.receipt_run_id == prior.receipt_run_id
        )
        if not unchanged:
            raise PairedRunStoreError("observed facts cannot downgrade or flip")
    if prior.infrastructure_status is InfrastructureStatus.INFRA_ERROR:
        unchanged = (
            candidate.infrastructure_status is InfrastructureStatus.INFRA_ERROR
            and candidate.receipt_ref == prior.receipt_ref
            and candidate.receipt_run_id == prior.receipt_run_id
            and candidate.receipt_status == prior.receipt_status
        )
        if not unchanged:
            raise PairedRunStoreError("infrastructure facts cannot downgrade or flip")
    if prior.behavior_verdict is not BehaviorVerdict.NOT_OBSERVED and (
        candidate.behavior_verdict is not prior.behavior_verdict
    ):
        raise PairedRunStoreError("behavior verdicts cannot flip")
