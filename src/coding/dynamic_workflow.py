from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Mapping, Sequence

from ..ingress import compact_source_metadata
from .dynamic_workflow_contracts import (
    CLAIM_BOUNDARY,
    DYNAMIC_WORKFLOW_CHART_SCHEMA_VERSION,
    DYNAMIC_WORKFLOW_LANES,
    DYNAMIC_WORKFLOW_MESSAGE_PROJECTION_SCHEMA_VERSION,
    DYNAMIC_WORKFLOW_SCHEMA_VERSION,
    PREPARED_NOT_OBSERVED,
)
from .dynamic_workflow_privacy import goal_payload
from .dynamic_workflow_specs import (
    DEFAULT_CRITICS,
    DEFAULT_IMPLEMENTERS,
    DEFAULT_PLANNERS,
    DEFAULT_REPORTER,
    DEFAULT_REVIEWERS,
    SUPPORTED_TARGET_TYPES,
    AgentSpec,
    agent_specs,
    parse_agent_spec,
)
from .executor_capability_snapshots import (
    ExecutorCapabilitySnapshotError,
    executor_capability_snapshot_path,
    read_matching_executor_capability_snapshot,
)


def build_dynamic_coding_workflow(
    goal: str,
    *,
    source: str = "generic",
    planners: Sequence[str] | None = None,
    critics: Sequence[str] | None = None,
    implementers: Sequence[str] | None = None,
    reviewers: Sequence[str] | None = None,
    reporter: str | None = None,
    source_metadata: Mapping[str, object] | None = None,
    capability_snapshot_directory: Path | None = None,
) -> dict[str, object]:
    normalized_goal = " ".join(goal.split())
    if not normalized_goal:
        raise ValueError("dynamic workflow goal is required")
    metadata = _source_metadata(source_metadata)

    planner_specs = agent_specs(planners, default_specs=DEFAULT_PLANNERS)
    critic_specs = agent_specs(critics, default_specs=DEFAULT_CRITICS)
    implementer_specs = agent_specs(implementers, default_specs=DEFAULT_IMPLEMENTERS)
    reviewer_specs = agent_specs(reviewers, default_specs=DEFAULT_REVIEWERS)
    reporter_spec = parse_agent_spec(reporter or DEFAULT_REPORTER)

    stages = _build_stages(planner_specs, critic_specs, implementer_specs, reviewer_specs, reporter_spec)
    _bind_persisted_executor_capability_snapshots(stages, capability_snapshot_directory)
    edges = _build_edges(stages)
    workflow_id = _workflow_id(normalized_goal, stages, edges, source=source, source_metadata=metadata)
    alt_text = "Dynamic coding workflow chart with typed orchestration target assignments."
    payload: dict[str, object] = {
        "schema_version": DYNAMIC_WORKFLOW_SCHEMA_VERSION,
        "workflow_id": workflow_id,
        "status": PREPARED_NOT_OBSERVED,
        "source": source,
        "goal": goal_payload(normalized_goal),
        "routing_policy": {
            "strategy": "cost_risk_capability_target_routing",
            "status": PREPARED_NOT_OBSERVED,
            "decision_inputs": [
                "stage_role",
                "target_type",
                "model_capability",
                "runtime_capability",
                "cost_tier",
                "risk_gate",
            ],
            "claim_boundary": (
                "Routing policy is a prepared recommendation until target selection and dispatch evidence are "
                "recorded."
            ),
        },
        "target_selection": {
            "selection_unit": "typed_orchestration_target",
            "status": PREPARED_NOT_OBSERVED,
            "supported_target_types": list(SUPPORTED_TARGET_TYPES),
            "default_policy": (
                "Defaults describe dynamic target pools; no concrete model, runtime, wrapper, tool, or agent is "
                "selected until an operator or runtime records target evidence."
            ),
            "decision_inputs": [
                "stage_role",
                "target_type",
                "model_capability",
                "runtime_capability",
                "cost_tier",
                "risk_gate",
            ],
            "claim_boundary": (
                "Target selection is prepared guidance until dispatch evidence records the chosen model, runtime, "
                "wrapper, tool, or agent surface."
            ),
        },
        "stages": stages,
        "edges": edges,
        "chart": {
            "schema_version": DYNAMIC_WORKFLOW_CHART_SCHEMA_VERSION,
            "format": "svg",
            "status": PREPARED_NOT_OBSERVED,
            "chart_path": "",
            "alt_text": alt_text,
        },
        "message_projection": {
            "schema_version": DYNAMIC_WORKFLOW_MESSAGE_PROJECTION_SCHEMA_VERSION,
            "status": PREPARED_NOT_OBSERVED,
            "attachments": [{"kind": "image", "format": "svg", "path": "", "alt_text": alt_text}],
        },
        "observed_evidence_required": [
            "operator_acceptance_observed",
            "target_selection_observed",
            "runtime_dispatch_observed",
            "worker_result_observed",
            "review_observed",
            "verification_observed",
        ],
        "prepared_is_not": [
            "not execution",
            "not model selection",
            "not model invocation",
            "not target selection",
            "not runtime dispatch",
            "not implementation",
            "not code review",
            "not CI",
            "not merge-readiness",
            "not merge evidence",
        ],
        "claim_boundary": CLAIM_BOUNDARY,
        "next_action": "record_runtime_observations_when_dispatch_happens",
    }
    if metadata:
        payload["source_metadata"] = metadata
    return payload


def _bind_persisted_executor_capability_snapshots(stages: list[dict[str, object]], directory: Path | None) -> None:
    if directory is None:
        return
    for stage in stages:
        target = stage.get("target")
        if not isinstance(target, str) or not target:
            continue
        try:
            path = executor_capability_snapshot_path(directory, target)
        except ExecutorCapabilitySnapshotError:
            continue
        snapshot = read_matching_executor_capability_snapshot(path, expected_executor=target)
        if snapshot is not None:
            stage["executor_capability_snapshot"] = snapshot


def _build_stages(
    planners: Sequence[AgentSpec],
    critics: Sequence[AgentSpec],
    implementers: Sequence[AgentSpec],
    reviewers: Sequence[AgentSpec],
    reporter: AgentSpec,
) -> list[dict[str, object]]:
    intake = AgentSpec("hermes", "omh", "Hermes/OMH intake", "wrapper", "wrapper")
    stages = [intake.stage(stage_id="intake-1", lane="intake", role="goal_intake", gate="goal_received", order=0)]
    stages.extend(
        _stages_for(planners, lane="planning", role="planner", gate="plan_prepared", prefix="plan", offset=10)
    )
    stages.extend(
        _stages_for(
            critics,
            lane="critique",
            role="critic",
            gate="critic_approval_required",
            prefix="critique",
            offset=20,
        )
    )
    stages.extend(
        _stages_for(
            implementers,
            lane="implementation",
            role="implementation_owner",
            gate="handoff_prepared_after_critique",
            prefix="implement",
            offset=30,
        )
    )
    stages.extend(
        _stages_for(
            reviewers,
            lane="review",
            role="independent_reviewer",
            gate="independent_review_required",
            prefix="review",
            offset=40,
        )
    )
    stages.append(
        reporter.stage(stage_id="report-1", lane="report", role="report_owner", gate="report_prepared", order=50)
    )
    return stages


def _stages_for(
    specs: Sequence[AgentSpec], *, lane: str, role: str, gate: str, prefix: str, offset: int
) -> list[dict[str, object]]:
    return [
        spec.stage(stage_id=f"{prefix}-{index}", lane=lane, role=role, gate=gate, order=offset + index)
        for index, spec in enumerate(specs, start=1)
    ]


def _build_edges(stages: Sequence[dict[str, object]]) -> list[dict[str, str]]:
    by_lane = {lane: [str(stage["id"]) for stage in stages if stage["lane"] == lane] for lane in DYNAMIC_WORKFLOW_LANES}
    edges: list[dict[str, str]] = []
    _connect(edges, by_lane["intake"], by_lane["planning"], "goal_to_plan")
    _connect(edges, by_lane["planning"], by_lane["critique"], "plan_to_critique")
    _connect(edges, by_lane["critique"], by_lane["implementation"], "approved_plan_to_fanout")
    _connect(edges, by_lane["implementation"], by_lane["review"], "implementation_to_review")
    _connect(edges, by_lane["review"], by_lane["report"], "review_to_report")
    return edges


def _connect(edges: list[dict[str, str]], sources: Sequence[str], targets: Sequence[str], label: str) -> None:
    for source in sources:
        for target in targets:
            edges.append({"from": source, "to": target, "label": label})


def _source_metadata(metadata: Mapping[str, object] | None) -> dict[str, str]:
    return compact_source_metadata(metadata)


def _workflow_id(
    goal: str,
    stages: Sequence[dict[str, object]],
    edges: Sequence[dict[str, str]],
    *,
    source: str,
    source_metadata: dict[str, str],
) -> str:
    raw = json.dumps(
        {"goal": goal, "source": source, "source_metadata": source_metadata, "stages": stages, "edges": edges},
        sort_keys=True,
    ).encode("utf-8")
    return "dynamic-" + sha256(raw).hexdigest()[:12]
