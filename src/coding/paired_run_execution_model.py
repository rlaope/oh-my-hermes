"""Typed metadata-only execution records for committed paired-run plans."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias

from .context_safety import compact_visible_text, redact_absolute_paths
from .hermes_child_receipts import VerifiedHermesChildReceipt
from .paired_run_dispatch_model import PairedRunDispatchCell, PairedRunDispatchPlan


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class PairedRunExecutionError(RuntimeError):
    """An expected external-boundary execution failure."""


class PairedRunWorkspaceFailure(PairedRunExecutionError):
    """The injected workspace factory could not prepare a workspace."""

    def __init__(
        self,
        message: str,
        *,
        cleanup_succeeded: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.cleanup_succeeded = cleanup_succeeded


class PairedRunRunnerFailure(PairedRunExecutionError):
    """The injected runner reported an expected execution failure."""


class PairedRunCleanupFailure(PairedRunExecutionError):
    """The injected cleaner reported an expected cleanup failure."""


@dataclass(frozen=True, slots=True)
class PairedRunWorkspace:
    """Opaque workspace handle passed unchanged between injected boundaries."""

    workspace_id: str


class ExecutionState(StrEnum):
    """Closed terminal outcomes reported by the paired-run execution boundary."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"
    RATE_LIMITED = "rate_limited"
    CRASHED = "crashed"
    PARTIAL = "partial"
    CLEANUP_FAILED = "cleanup_failed"
    UNAUTHENTICATED = "unauthenticated"


class CrashDetailState(StrEnum):
    """Closed vocabulary for what happened to a crashed cell's message."""

    RETAINED = "retained"
    WITHHELD = "withheld"
    EMPTY = "empty"


# A contained cell's exception is the only surviving trace of why it crashed, so
# it is recorded rather than discarded. The record reaches a metadata artifact,
# so the message is bounded, path-redacted, control-stripped, and withheld whole
# when it looks like it carries a secret -- the posture
# `fanout_failure_diagnostics` applies to captured child output, minus the
# closed line allowlist, which would erase the cause this record exists to
# carry. `EMPTY` and `WITHHELD` stay distinct because a reader must be able to
# tell an exception that carried no message from one whose message was screened.
MAX_CRASH_ERROR_TYPE_CHARS = 80
MAX_CRASH_DETAIL_CHARS = 200
_UNSAFE_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
_UNSAFE_ERROR_TYPE_RE = re.compile(r"[^A-Za-z0-9_.]")
_SECRET_MARKER_RE = re.compile(
    r"(?i:authorization\s*:|bearer\s|api[_-]?key\s*[=:]|password\s*[=:]|"
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----)|sk-|github_pat_|gh[pousr]_|AKIA|AIza"
)


@dataclass(frozen=True, slots=True)
class PairedRunCrashReason:
    """Bounded, sanitized record of what raised inside a contained cell."""

    error_type: str
    detail: str
    detail_state: CrashDetailState

    @property
    def label(self) -> str:
        """Return the one-line cause for a caller reporting this cell's state."""
        if self.detail_state is CrashDetailState.RETAINED:
            return f"{self.error_type}: {self.detail}"
        return f"{self.error_type} ({self.detail_state.value} detail)"


def crash_reason_for(exc: BaseException) -> PairedRunCrashReason:
    """Record what raised, without letting raw exception text reach a caller."""
    error_type = _UNSAFE_ERROR_TYPE_RE.sub("", type(exc).__name__)[
        :MAX_CRASH_ERROR_TYPE_CHARS
    ] or "Exception"
    raw = str(exc)
    # Screen the unmodified text: redaction rewrites paths, never markers.
    if _SECRET_MARKER_RE.search(raw):
        return PairedRunCrashReason(error_type, "", CrashDetailState.WITHHELD)
    detail = compact_visible_text(
        _UNSAFE_CONTROL_RE.sub(" ", redact_absolute_paths(raw)),
        max_chars=MAX_CRASH_DETAIL_CHARS,
    )
    if not detail:
        return PairedRunCrashReason(error_type, "", CrashDetailState.EMPTY)
    return PairedRunCrashReason(error_type, detail, CrashDetailState.RETAINED)


@dataclass(frozen=True, slots=True)
class PairedRunExecutionLimits:
    """Explicit runner limits; omitted limits are inferred from the frozen waves."""

    global_concurrency: int
    executor_concurrency: dict[str, int]
    provider_concurrency: dict[str, int]


@dataclass(frozen=True, slots=True)
class PairedRunExecutionOutcome:
    """A runner result or persisted metadata-only terminal execution record."""

    state: ExecutionState
    receipt: VerifiedHermesChildReceipt | None
    cell: PairedRunDispatchCell | None = None
    cleanup_succeeded: bool | None = None
    authenticated: bool = False
    reused: bool = False
    crash_reason: PairedRunCrashReason | None = None


@dataclass(frozen=True, slots=True)
class PairedRunExecutionReport:
    """The completed plan projection. It carries no merge or content payload."""

    plan: PairedRunDispatchPlan
    receipts: tuple[PairedRunExecutionOutcome, ...]

    @property
    def fan_in_ready(self) -> bool:
        return self.plan.decision_ready and all(
            receipt.state is not ExecutionState.UNAUTHENTICATED
            for receipt in self.receipts
        )

    def metadata(self) -> dict[str, JsonValue]:
        """Return only stable execution metadata suitable for caller persistence."""
        return {
            "decision_id": self.plan.decision_id,
            "fan_in_ready": self.fan_in_ready,
            "cells": [
                {
                    "workspace_id": item.cell.workspace_id if item.cell else "",
                    "state": item.state.value,
                    "authenticated": item.authenticated,
                    "cleanup_succeeded": item.cleanup_succeeded,
                    "reused": item.reused,
                    "receipt_ref": item.receipt.receipt_ref if item.receipt else "",
                    "crash_reason": _crash_reason_payload(item.crash_reason),
                }
                for item in self.receipts
            ],
        }


def _crash_reason_payload(reason: PairedRunCrashReason | None) -> JsonValue:
    if reason is None:
        return None
    return {
        "error_type": reason.error_type,
        "detail": reason.detail,
        "detail_state": reason.detail_state.value,
    }
