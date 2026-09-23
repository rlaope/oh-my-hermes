"""Post-GREEN fanout diagnostic execution hook."""

from __future__ import annotations

import re

from .diagnostic_execution import DiagnosticExecutionEngine, DiagnosticExecutionRequest


_FIXED_COMMIT = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


def run_post_green_diagnostics(
    engine: DiagnosticExecutionEngine | None,
    *,
    owner: str,
    workspace_id: str,
    workspace_path: str = "",
    baseline_revision: str,
    end_revision: str,
    verification_passed: bool,
    producer_evidence: bool,
) -> dict[str, object] | None:
    """Run diagnostics only for a clean, fixed revision with passing GREEN evidence.

    Diagnostics are observation metadata. A non-clean diagnostic outcome holds
    only that metadata; it never changes the unit's verification ladder.
    """
    if (
        engine is None
        or not engine.settings.enabled
        or not verification_passed
        or not producer_evidence
        or _FIXED_COMMIT.fullmatch(baseline_revision) is None
        or _FIXED_COMMIT.fullmatch(end_revision) is None
    ):
        return None
    execution = engine.execute(
        DiagnosticExecutionRequest(
            owner=owner,
            workspace_id=workspace_id,
            baseline_revision=baseline_revision,
            end_revision=end_revision,
            workspace_path=workspace_path,
        )
    )
    evidence = [result.evidence for result in execution.results]
    return {
        "diagnostic_status": "observed" if execution.status == "ok" else "held",
        "diagnostic_execution_status": execution.status,
        "diagnostic_evidence_refs": [
            f"language_diagnostic:{record['record_id']}" for record in evidence
        ],
        "language_diagnostic_evidence": evidence,
    }
