from __future__ import annotations


DIMENSION_IDS = (
    "route_selection",
    "guidance_depth",
    "native_execution_availability",
    "provider_execution_availability",
    "artifact_verification",
    "comparative_outcome_quality",
)


def standalone_capability_impact_report() -> dict[str, object]:
    statuses = {
        "route_selection": "not_observed_in_fallback",
        "guidance_depth": "partially_proven",
        "native_execution_availability": "requires_host_observation",
        "provider_execution_availability": "requires_provider_observation",
        "artifact_verification": "partially_proven",
        "comparative_outcome_quality": "requires_external_evaluator",
    }
    boundaries = {
        "route_selection": "The fallback bundle cannot run package-owned routing corpora.",
        "guidance_depth": "Static fallback metadata is inspectable but does not prove outcome quality.",
        "native_execution_availability": "Registration metadata requires host load and invocation evidence.",
        "provider_execution_availability": "External provider availability must be observed per installation.",
        "artifact_verification": "Hook presence is guidance, not verification evidence.",
        "comparative_outcome_quality": "Comparative quality requires an external paired evaluator.",
    }
    return {
        "schema_version": "omh_capability_impact_report/v1",
        "source": "standalone_plugin_bundle_fallback",
        "degraded": True,
        "determinism": "static_plugin_metadata_no_runtime_clock",
        "verdict": "insufficient_package_context",
        "score_policy": (
            "No aggregate score: route accuracy, guidance, host availability, provider availability, "
            "artifact verification, and comparative quality are separate claims."
        ),
        "dimensions": [
            {"id": id_, "status": statuses[id_], "evidence": {}, "boundary": boundaries[id_]}
            for id_ in DIMENSION_IDS
        ],
        "route_selection": {
            "fixed_precision": {"passed": 0, "total": 0, "overroutes": 0, "missed_interventions": 0},
            "common_requests": {
                "passed": 0,
                "total": 0,
                "coverage_percent": 0.0,
                "target_met": False,
                "popular_plugin_families": {"covered": 0, "total": 0, "weighted_coverage_percent": 0.0},
            },
            "representative": {
                "passed": 0,
                "total": 0,
                "failed": [],
                "evidence_class": "implementation_smoke",
            },
        },
        "claim_boundaries": [
            "Prepared or registered capability is not observed execution.",
            "Install the package to evaluate deterministic routing contracts.",
            "Comparative quality remains unproven until an external paired evaluator is run.",
        ],
    }
