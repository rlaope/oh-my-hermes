from __future__ import annotations

ACHIEVEMENT_EVIDENCE_SCHEMA_VERSION = "achievement_evidence_contract/v1"


def achievement_evidence_contracts() -> list[dict[str, object]]:
    return [
        {
            "schema_version": ACHIEVEMENT_EVIDENCE_SCHEMA_VERSION,
            "id": "hermes_achievements_observation",
            "display_name": "Hermes achievements observation",
            "source": (
                "Local hermes-achievements plugin artifacts: scan_snapshot.json, state.json, "
                "and agent_summary.json when the upstream plugin writes it."
            ),
            "claim_kind": "observed_badge_metadata",
            "claim_fields": [
                "badge_id",
                "name",
                "tier",
                "category",
                "state",
                "progress_percent",
                "unlocked_at",
            ],
            "profile_fields": [
                "strengths",
                "gaps",
                "top_tier",
                "unlocked_count",
                "total_count",
                "derivation",
            ],
            "evidence_rule": (
                "A badge or profile field may be claimed only when it was read from local hermes-achievements "
                "plugin artifacts; OMH never rescans Hermes session history and never recomputes unlocks."
            ),
            "degradation_rule": (
                "Missing, corrupt, or unknown-shaped artifacts degrade to a not_observed report instead of "
                "failing or guessing."
            ),
            "not_evidence_for": [
                "productivity",
                "code_quality",
                "execution",
                "review",
                "ci",
                "merge_readiness",
                "merge",
            ],
            "surfaces": [
                "omh achievements",
                "hud full preset",
                "context brief achievements_profile",
                "achievements skill",
            ],
        }
    ]
