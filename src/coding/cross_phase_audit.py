"""Cross-phase evidence checks for memory, branch, and Git handoffs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .branch_policy import verify_repository_branch
from .git_checkpoint import verify_git_checkpoint

CROSS_PHASE_AUDIT_SCHEMA_VERSION = "cross_phase_audit/v1"


def _check(name: str, ok: bool, reason: str, **evidence: Any) -> dict[str, Any]:
    return {"name": name, "ok": ok, "reason": reason, "evidence": evidence}


def audit_memory_retrieval(pack: Any, *, token_budget: int = 8192) -> dict[str, Any]:
    """Validate bounded retrieval telemetry without claiming task success."""
    if not isinstance(pack, dict):
        return _check("memory_retrieval", False, "missing_recall_pack")
    observation = pack.get("retrieval_observation")
    if not isinstance(observation, dict):
        return _check("memory_retrieval", False, "missing_retrieval_observation")
    if observation.get("schema_version") != "memory_retrieval_observation/v1":
        return _check(
            "memory_retrieval",
            False,
            "conflicting_observation_schema",
            schema_version=observation.get("schema_version"),
        )
    warnings = pack.get("freshness_warnings")
    if isinstance(warnings, list) and warnings:
        return _check(
            "memory_retrieval",
            False,
            "stale_recall_evidence",
            freshness_warnings=warnings[:8],
        )
    estimate = observation.get("selected_token_estimate")
    if not isinstance(estimate, int) or estimate < 0:
        return _check(
            "memory_retrieval",
            False,
            "invalid_token_estimate",
            selected_token_estimate=estimate,
        )
    if token_budget < 1:
        return _check(
            "memory_retrieval", False, "invalid_token_budget", token_budget=token_budget
        )
    if estimate > token_budget:
        return _check(
            "memory_retrieval",
            False,
            "retrieval_over_budget",
            selected_token_estimate=estimate,
            token_budget=token_budget,
        )
    return _check(
        "memory_retrieval",
        True,
        "bounded_retrieval_observed",
        selected_records=observation.get("selected_records", 0),
        excluded_records=observation.get("excluded_records", 0),
        selected_token_estimate=estimate,
        token_budget=token_budget,
    )


def run_cross_phase_audit(
    repo_root: str | Path = ".",
    *,
    seed_id: str = "",
    checkpoint: dict[str, Any] | None = None,
    memory_pack: Any = None,
    token_budget: int = 8192,
) -> dict[str, Any]:
    """Run read-only continuity checks and return stable machine-readable evidence."""
    root = Path(repo_root).expanduser().resolve()
    branch = verify_repository_branch(root, seed_id=seed_id)
    checks = [
        _check(
            "feature_branch",
            branch.get("status") == "allowed",
            "feature_branch_policy_satisfied"
            if branch.get("status") == "allowed"
            else "feature_branch_policy_refused",
            **branch,
        ),
        audit_memory_retrieval(memory_pack, token_budget=token_budget),
    ]
    if checkpoint is None:
        checks.append(_check("git_checkpoint", False, "missing_checkpoint"))
    else:
        verified = verify_git_checkpoint(checkpoint, root)
        checks.append(
            _check(
                "git_checkpoint",
                bool(verified.get("ok")),
                "checkpoint_continuity_verified"
                if verified.get("ok")
                else "checkpoint_continuity_refused",
                verification=verified,
            )
        )
    return {
        "schema_version": CROSS_PHASE_AUDIT_SCHEMA_VERSION,
        "repo_root": str(root),
        "seed_id": seed_id,
        "checks": checks,
        "ok": all(bool(item["ok"]) for item in checks),
        "claim_boundary": (
            "Cross-phase audit reports bounded local evidence only; it does not prove implementation, model use, "
            "tests, review, CI, merge-readiness, or merge."
        ),
    }
