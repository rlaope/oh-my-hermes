"""Immutable post-integration fanout final-review hook."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
import re
from typing import Protocol

from .final_review_wave import (
    LANE_ORDER,
    FinalReviewWave,
    ImmutableRevision,
    LaneObservation,
    LaneState,
    ReviewLens,
    WaveVerdict,
)


_FIXED_REVISION = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


class FinalReviewWaveEngine(Protocol):
    """Caller-owned executor for one already-configured read-only review wave."""

    def execute(
        self,
        revision: ImmutableRevision,
        observe: Callable[[LaneObservation], None],
    ) -> FinalReviewWave: ...


def run_final_review_after_integration(
    engine: FinalReviewWaveEngine | None,
    *,
    integrated_revision: str,
    integration_green: bool,
    producer_evidence: bool,
    workspace_revision: Callable[[], str | None] | None = None,
) -> dict[str, object] | None:
    """Execute one immutable review wave without changing dispatch readiness."""
    if engine is None:
        return None
    if _FIXED_REVISION.fullmatch(integrated_revision) is None:
        return _aggregate(integrated_revision, "BLOCK")
    if not integration_green or not producer_evidence:
        return _aggregate(integrated_revision, "HOLD")
    if (
        workspace_revision is None
        or workspace_revision() != integrated_revision
    ):
        return _aggregate(integrated_revision, "BLOCK")
    revision = ImmutableRevision(integrated_revision)
    observed: list[LaneObservation] = []
    wave = engine.execute(revision, observed.append)
    if workspace_revision() != integrated_revision:
        return _aggregate(integrated_revision, "BLOCK")
    if (
        wave.integration is None
        or not wave.integration.completed
        or wave.integration.revision != revision
        or tuple(lane.lens for lane in wave.lanes) != LANE_ORDER
        or any(lane.read_only.allows_mutation or lane.bound_revision != revision for lane in wave.lanes)
    ):
        return _aggregate(integrated_revision, "BLOCK")
    observations = _observations_by_lens(observed)
    if observations is None or any(
        observations[lane.lens]
        != LaneObservation(lane.lens, lane.state, lane.observed_revision)
        for lane in wave.lanes
    ):
        return _aggregate(integrated_revision, "BLOCK")
    assessment = wave.assess()
    if any(lane.observed_revision != revision for lane in wave.lanes):
        return _aggregate(integrated_revision, "BLOCK", assessment.blocking_lens.value if assessment.blocking_lens else "")
    if assessment.verdict is WaveVerdict.PASS and any(
        lane.state is not LaneState.COMPLETED for lane in wave.lanes
    ):
        return _aggregate(integrated_revision, "BLOCK")
    records = [
        {
            "lens": lane.lens.value,
            "state": lane.state.value,
            "revision": integrated_revision,
            "execution_observed": True,
            "execution_ref": _execution_ref(integrated_revision, observations[lane.lens]),
        }
        for lane in wave.lanes
    ]
    result = _aggregate(
        integrated_revision,
        assessment.verdict.value,
        assessment.blocking_lens.value if assessment.blocking_lens else "",
    )
    result["final_review_records"] = records
    return result


def _observations_by_lens(
    observations: list[LaneObservation],
) -> dict[ReviewLens, LaneObservation] | None:
    by_lens: dict[ReviewLens, LaneObservation] = {}
    for observation in observations:
        if observation.lens in by_lens:
            return None
        by_lens[observation.lens] = observation
    return by_lens if tuple(lens for lens in LANE_ORDER if lens in by_lens) == LANE_ORDER else None


def _execution_ref(revision: str, observation: LaneObservation) -> str:
    material = (
        f"{revision}\0{observation.lens.value}\0"
        f"{observation.state.value}\0{observation.revision.value}"
    ).encode("ascii")
    return f"final-review:{hashlib.sha256(material).hexdigest()}"


def _aggregate(revision: str, verdict: str, blocking_lens: str = "") -> dict[str, object]:
    aggregate: dict[str, str] = {"revision": revision, "verdict": verdict}
    if blocking_lens:
        aggregate["blocking_lens"] = blocking_lens
    return {
        "final_review_status": verdict,
        "final_review_aggregate": aggregate,
    }
