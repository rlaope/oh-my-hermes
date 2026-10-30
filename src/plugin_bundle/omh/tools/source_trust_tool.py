"""Hermes-callable surface for the source-trust ceiling.

Hermes learns what OMH *describes* from installed skill prose, but the
source-trust ceiling is a mechanical guard, and a guard that only exists in
prose is the thing `omh.workflows.source_trust` was written to replace. This
tool is the path where Hermes hands over the claims it gathered and OMH actually
runs the ceiling on them, rather than asking a model to remember a rule.

Fail-closed on degradation, which is the one design decision here worth stating.
Every other tool in this bundle answers from a standalone fallback when the
`omh` package is not importable, because a partial answer beats no answer for
status, routing hints, or capability listings. A ceiling is different: an
enforcement surface that cannot enforce must not return something a reader can
mistake for an enforced result. So when the backend is missing this returns
`degraded: true`, no summary, and says the ceiling did not run.
"""

from __future__ import annotations

import json
from typing import Any

from ..host_observation import attach_public_observation, observe_plugin_tool_call

# Bounded so one call cannot hand over an unbounded transcript. Matches the
# spirit of the eight-row rejection cap inside the summary itself.
_MAX_CLAIMS = 64

_UNAVAILABLE_REASON = (
    "The OMH package backend is not importable, so the source-trust ceiling did not run. "
    "No summary is returned: an unenforced answer must not read as an enforced one."
)

OMH_SOURCE_TRUST_SCHEMA = {
    "name": "omh_source_trust",
    "description": (
        "Apply the OMH source-trust ceiling. For gathered claims, report what class of source stands "
        "behind each claim and what those claims collectively support. A practitioner heuristic may "
        "inform approach and never becomes an established finding, and no source class settles "
        "completion. This reports source class, never whether a claim is true; it is not observation, "
        "execution, verification, review, CI, or merge evidence."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "topic": {
                "type": "string",
                "description": "One bounded line naming what these claims are about.",
            },
            "claims": {
                "type": "array",
                "description": f"Up to {_MAX_CLAIMS} claims to classify.",
                "items": {
                    "type": "object",
                    "properties": {
                        "tier": {
                            "type": "string",
                            "enum": ["upstream_official", "practitioner_heuristic", "unattributed"],
                            "description": "Stated by the caller. OMH never infers trust from a source.",
                        },
                        "claim_kind": {
                            "type": "string",
                            "enum": ["approach", "finding", "completion"],
                            "description": "What the claim asserts. No tier may back completion.",
                        },
                        "claim": {"type": "string", "description": "One bounded line, no links or paths."},
                        "source_id": {
                            "type": "string",
                            "description": (
                                "Opaque source identifier, not a URL - for example a source-finder "
                                "candidate_id. Omit only for an unattributed claim."
                            ),
                        },
                        "recorded_at": {"type": "string", "description": "Opaque timestamp reference."},
                    },
                },
            },
        },
    },
}


def omh_source_trust_handler(args: dict, **kwargs) -> str:
    observation = observe_plugin_tool_call("omh_source_trust", args, kwargs)
    topic = str(args.get("topic", "") or "").strip()
    rows = args.get("claims")
    rows = list(rows) if isinstance(rows, list) else []
    payload = _apply_ceiling(topic=topic, rows=rows[:_MAX_CLAIMS], dropped=max(0, len(rows) - _MAX_CLAIMS))
    return json.dumps(attach_public_observation(payload, observation), sort_keys=True)


def _apply_ceiling(*, topic: str, rows: list[Any], dropped: int) -> dict[str, Any]:
    try:
        from omh.workflows.source_trust import (
            SOURCE_TRUST_CLAIM_BOUNDARY,
            SourceTrustError,
            build_source_trust_claim,
            summarize_source_trust,
        )
    except (ImportError, ModuleNotFoundError):
        return _unavailable()

    minted: list[dict[str, Any]] = []
    refused: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            refused.append({"index": index, "reason": "claim must be an object"})
            continue
        try:
            minted.append(
                build_source_trust_claim(
                    tier=str(row.get("tier", "") or ""),
                    claim_kind=str(row.get("claim_kind", "") or ""),
                    claim=str(row.get("claim", "") or ""),
                    recorded_at=str(row.get("recorded_at", "") or ""),
                    source_ref=str(row.get("source_id", "") or ""),
                )
            )
        except SourceTrustError as exc:
            # The refusal IS the product here. A claim the ceiling rejects is
            # reported with its reason rather than dropped, so the caller can
            # see which tier overreached and restate it.
            refused.append({"index": index, "reason": str(exc)[:200]})

    try:
        summary = summarize_source_trust(topic=topic or "unnamed topic", claims=minted)
    except SourceTrustError as exc:
        return {
            "plugin_tool": "omh_source_trust",
            "source": "package_source_trust_error",
            "degraded": True,
            "privacy": "metadata_only",
            "ceiling_applied": False,
            "error": "package_backend_error",
            "error_type": type(exc).__name__,
            "reason": str(exc)[:200],
            "claim_boundary": SOURCE_TRUST_CLAIM_BOUNDARY,
        }

    return {
        "plugin_tool": "omh_source_trust",
        "source": "package_source_trust",
        "degraded": False,
        "privacy": "metadata_only",
        "ceiling_applied": True,
        "summary": summary,
        "accepted_count": len(minted),
        "refused_count": len(refused),
        "refused_claims": refused[:8],
        "dropped_over_limit": dropped,
        "claim_boundary": SOURCE_TRUST_CLAIM_BOUNDARY,
    }


def _unavailable() -> dict[str, Any]:
    return {
        "plugin_tool": "omh_source_trust",
        "source": "standalone_plugin_bundle_fallback",
        "degraded": True,
        "privacy": "metadata_only",
        "ceiling_applied": False,
        "reason": _UNAVAILABLE_REASON,
        "claim_boundary": (
            "The source-trust ceiling did not run in this environment. Nothing here reports what a "
            "claim may support, and no statement is observation, execution, verification, review, "
            "CI, or merge evidence."
        ),
    }
