"""Owner-neutral run health projection (`run_health_summary/v1`).

A progress story says WHAT happened. It does not say why a run is slow, stale,
retrying, or missing the evidence that would settle it -- and every coding owner
narrates that in its own words, so the same unhealthy run reads differently
depending on who was executing it. This module is the one answer shape.

It projects health over NORMALIZED progress events
(`coding.owner_progress_normalization`), never over raw per-owner event shapes.
That is the entire mechanism behind "the same normalized events produce the same
health summary across supported coding owners": a codex run narrating
`dispatch_to_executor / item.completed / turn.completed` and a Claude Code run
narrating `system / assistant / result` normalize to the same three words, so
they project byte-identical summaries apart from `owner_attribution`.
`health_digest` makes that equality one comparison instead of a field-by-field
walk.

`run_health_summary/v2` (issue #1296) is the same projection plus one optional
COMMITTED section: `critical_path_health/v1`, a projection produced by
`omh.runtime.critical_path_health` and embedded as-is. The v1 key sets are
exact in both directions, so v1 is frozen -- a summary cannot grow an
optional section without breaking every v1 record or silently widening the
schema. The section therefore arrives through `run_health_input/v2` and
upgrades the summary to `run_health_summary/v2`; when it is absent, the v1
parse, render, and digest bytes are produced exactly. The section is inside
`health_digest`, so two runs whose critical paths were measured under
incompatible executor/model/environment metadata never compare equal.

The equality is not vacuous. An owner whose stream this repo cannot read carries
a lower evidence ceiling, so its `full_tests_passed` normalizes to
`unmapped_source_event` rather than `tests_passed`; the resulting summary
differs, and it should.

Boundaries, in order of importance:

- Three distinct absences, never an estimate. Every metric is a
  `{state, value, reason}` triple, and only `observed` carries a number.
  `unknown` means the EVENT that bounds the metric was never observed.
  `unavailable` means the event was observed but carried no clock, so the value
  cannot be measured. A genuine `0` -- no retries, or two boundary events
  sharing a millisecond -- is `observed` with value `0` and is therefore
  distinguishable from both. Nothing here ever substitutes `observed_at_ms`, the
  last event, or a neighbouring phase for a boundary it did not observe: a
  plausible number is worse than an honest absence, because only the absence can
  be noticed.
- No clock read. This module imports nothing that can tell the time. The
  observation instant arrives as `observed_at_ms` on the input, so the same
  input always projects a byte-identical summary. `health_digest` additionally
  excludes every now-dependent field (`_DIGEST_EXCLUDED_TOP_LEVEL`,
  `_DIGEST_EXCLUDED_METRICS`), so comparing two runs' health never turns into
  comparing two wall clocks.
- Metadata-only, and reporting only. A summary carries normalized event names,
  integers, and closed vocabulary words. It never carries prompts, tool output,
  file contents, secrets, or user text. It is not execution, verification,
  review, CI, merge-readiness, or merge evidence.
- No efficiency claim without a named baseline AND a named evaluator. A
  comparative `direction` is refused at parse time and again by
  `validate_run_health_summary`, so a payload asserting "faster" with nobody
  named cannot be built and cannot be read back. `gate` is derived from the two
  refs rather than declared, so it cannot be hand-set to agree with itself.
- Refuse a hand-edited record rather than render it.
  `validate_run_health_summary` checks the key set in both directions and
  re-derives every metric, the staleness verdict, the claim gate, the owner
  attribution, and the digest from `observations`. A record whose numbers were
  edited to look healthier fails; it is not shown.

Reading a summary (`run_health_summary/v1`)
-------------------------------------------

    run_id                  which run this is about
    owner_attribution       who owned the coding work, whether that owner has a
                            progress lane, and the evidence ceiling its stream
                            can carry -- the ONLY owner-dependent block, and the
                            only one excluded from `health_digest`
    observed_at_ms          the caller's observation instant; the freshness
                            anchor, and the only now-dependent input
    observations            the normalized event stream with its clocks, in
                            observed order -- everything below is derived from
                            this and nothing else
    metrics                 the closed metric set, each a state/value/reason
    staleness               fresh | stale | unknown | unavailable
    staleness_threshold_ms  the line `staleness` was drawn at
    efficiency_claim        direction, baseline_ref, evaluator_ref, derived gate
    health_digest           the owner-independent, now-independent fingerprint
    claim_boundary          what the summary is not
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import re
from typing import Any, Final

from ..coding.owner_progress_normalization import (
    NORMALIZED_PROGRESS_EVENT_TYPES,
    UNMAPPED_NORMALIZED_EVENT,
    normalize_owner_progress_event,
    owner_evidence_ceiling,
)
from ..system.metadata_safety import require_opaque_metadata_ref
from .run_health_critical_path import (
    committed_critical_path_health_errors,
    parse_committed_critical_path_health,
    render_critical_path_health_lines,
)


RUN_HEALTH_INPUT_SCHEMA_VERSION: Final[str] = "run_health_input/v1"
RUN_HEALTH_INPUT_V2_SCHEMA_VERSION: Final[str] = "run_health_input/v2"
RUN_HEALTH_SUMMARY_SCHEMA_VERSION: Final[str] = "run_health_summary/v1"
RUN_HEALTH_SUMMARY_V2_SCHEMA_VERSION: Final[str] = "run_health_summary/v2"

RUN_HEALTH_CLAIM_BOUNDARY: Final[str] = (
    "A run health summary is an OMH-local projection over normalized owner progress events. It is "
    "metadata-only observation, not execution, verification, review, CI, merge-readiness, or merge "
    "evidence, and it never asserts an efficiency improvement without a named baseline and a named "
    "evaluator."
)

# A phase is a POSITION in the run, not a bucket of similar-sounding words.
# Verification is split in two because "the tests started" and "the tests
# reported" are different positions, and a `tests_started` observed after a
# `tests_failed` is the canonical retry -- a single verification phase could not
# see it move backwards.
RUN_HEALTH_PHASES: Final[tuple[str, ...]] = (
    "dispatch",
    "execution",
    "verification_started",
    "verification_outcome",
    "completion",
)

# Where each normalized event places the run. `unmapped_source_event` is
# deliberately absent: a word this repo could not translate must not define a
# phase boundary, count as a retry, or close somebody else's phase. It is
# counted as an evidence gap instead, which is what it is.
_PHASE_BY_NORMALIZED_EVENT: Final[dict[str, str]] = {
    "executor_dispatched": "dispatch",
    "repo_exploration": "execution",
    "running_no_diff_observed": "execution",
    "diff_started": "execution",
    "progress_observed": "execution",
    "reported_change_not_observed": "execution",
    "tests_started": "verification_started",
    "tests_passed": "verification_outcome",
    "tests_failed": "verification_outcome",
    "executor_completed": "completion",
    "executor_blocked": "completion",
    "executor_failed": "completion",
    # A cancellation ends the run at the same rung the other three end it. It
    # is deliberately absent from `_FAILURE_CLASS_BY_NORMALIZED_EVENT`: a run
    # someone stopped observed no failure, and reporting one would attribute a
    # defect to work that was never allowed to reach a verdict.
    "executor_cancelled": "completion",
}

# Only phases that a LATER phase can close get a duration. `verification_outcome`
# and `completion` are instants that close earlier phases rather than spans of
# their own, so inventing a duration for them would mean inventing an end.
_PHASE_DURATION_METRIC: Final[dict[str, str]] = {
    "dispatch": "dispatch_phase_duration_ms",
    "execution": "execution_phase_duration_ms",
    "verification_started": "verification_phase_duration_ms",
}

# Ascending severity. `failure_class` is the highest-severity class observed, so
# a run that failed its tests and then reported the executor as failed reports
# the terminal failure rather than whichever event happened to come last.
RUN_HEALTH_FAILURE_CLASSES: Final[tuple[str, ...]] = (
    "no_failure_observed",
    "claim_not_corroborated",
    "executor_blocked",
    "verification_failed",
    "executor_failed",
)

_FAILURE_CLASS_BY_NORMALIZED_EVENT: Final[dict[str, str]] = {
    "reported_change_not_observed": "claim_not_corroborated",
    "executor_blocked": "executor_blocked",
    "tests_failed": "verification_failed",
    "executor_failed": "executor_failed",
}

RUN_HEALTH_METRIC_STATES: Final[tuple[str, ...]] = ("observed", "unavailable", "unknown")

# The bounding EVENT was never observed. Nothing on this list is fixable by a
# better clock.
_UNKNOWN_REASONS: Final[tuple[str, ...]] = (
    "no_observed_events",
    "fewer_than_two_observed_events",
    "phase_not_observed",
    "phase_not_closed_by_a_later_observed_phase",
    "observed_at_ms_precedes_the_last_observed_event",
)

# The event WAS observed and carried no clock. Nothing on this list is fixable
# by observing more events.
_UNAVAILABLE_REASONS: Final[tuple[str, ...]] = ("boundary_event_carried_no_timestamp",)

RUN_HEALTH_METRIC_REASONS: Final[tuple[str, ...]] = ("", *_UNKNOWN_REASONS, *_UNAVAILABLE_REASONS)

# Metric name -> value kind. The kind is what makes a mixed metric set safely
# validatable: a duration and a count are both nonnegative integers, a failure
# class is one closed word, and nothing else is accepted in a value slot.
RUN_HEALTH_METRIC_KINDS: Final[dict[str, str]] = {
    "dispatch_phase_duration_ms": "duration_ms",
    "evidence_gap_count": "count",
    "execution_phase_duration_ms": "duration_ms",
    "failure_class": "failure_class",
    "idle_duration_ms": "duration_ms",
    "retry_count": "count",
    "total_duration_ms": "duration_ms",
    "unobserved_phase_count": "count",
    "verification_phase_duration_ms": "duration_ms",
}

RUN_HEALTH_METRICS: Final[tuple[str, ...]] = tuple(sorted(RUN_HEALTH_METRIC_KINDS))

RUN_HEALTH_STALENESS_STATES: Final[tuple[str, ...]] = ("fresh", "stale", "unavailable", "unknown")

# Five minutes. A run that has said nothing for longer is reported stale; the
# threshold ships inside the summary so a reader never has to guess which line
# the verdict was drawn at.
RUN_HEALTH_STALENESS_THRESHOLD_MS: Final[int] = 300_000

RUN_HEALTH_EFFICIENCY_DIRECTIONS: Final[tuple[str, ...]] = ("unclaimed", "improved", "regressed", "unchanged")

RUN_HEALTH_EFFICIENCY_GATES: Final[tuple[str, ...]] = (
    "named_baseline_and_evaluator",
    "no_named_baseline_and_evaluator",
)

# Bounds. A health summary is a bounded projection an agent may poll, so the
# event list is capped rather than left to grow with the run.
MAX_RUN_HEALTH_EVENTS: Final[int] = 100
MAX_RUN_HEALTH_REF_CHARS: Final[int] = 120

_RUN_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")

_INPUT_KEYS: Final[frozenset[str]] = frozenset(
    {"schema_version", "run_id", "owner", "observed_at_ms", "events", "efficiency_claim"}
)
_INPUT_V2_KEYS: Final[frozenset[str]] = _INPUT_KEYS | {"critical_path_health"}
_INPUT_EVENT_KEYS: Final[frozenset[str]] = frozenset({"source_event", "at_ms"})
_INPUT_CLAIM_KEYS: Final[frozenset[str]] = frozenset({"direction", "baseline_ref", "evaluator_ref"})

_SUMMARY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "run_id",
        "owner_attribution",
        "observed_at_ms",
        "observations",
        "metrics",
        "staleness",
        "staleness_threshold_ms",
        "efficiency_claim",
        "health_digest",
        "claim_boundary",
    }
)
_SUMMARY_V2_KEYS: Final[frozenset[str]] = _SUMMARY_KEYS | {"critical_path_health"}
_ATTRIBUTION_KEYS: Final[frozenset[str]] = frozenset({"owner", "owner_supported", "evidence_ceiling"})
_OBSERVATION_KEYS: Final[frozenset[str]] = frozenset({"normalized_event", "at_ms"})
_METRIC_KEYS: Final[frozenset[str]] = frozenset({"state", "value", "reason"})
_SUMMARY_CLAIM_KEYS: Final[frozenset[str]] = frozenset({"direction", "baseline_ref", "evaluator_ref", "gate"})

# What `health_digest` refuses to fingerprint. `owner_attribution` is excluded so
# two owners producing the same normalized stream produce the same digest --
# that IS the cross-owner guarantee. The rest are the now-dependent fields; a
# digest that moved with the wall clock could never compare two runs.
_DIGEST_EXCLUDED_TOP_LEVEL: Final[tuple[str, ...]] = (
    "owner_attribution",
    "observed_at_ms",
    "staleness",
    "health_digest",
)
_DIGEST_EXCLUDED_METRICS: Final[tuple[str, ...]] = ("idle_duration_ms",)


@dataclass(frozen=True)
class RunHealthEvent:
    """One owner-narrated event, as supplied: the raw word and its clock, if any.

    `at_ms` is `None` when the event was observed without a clock. That is a
    different fact from "the event was never observed", and the metric states
    keep them apart.
    """

    source_event: str
    at_ms: int | None


@dataclass(frozen=True)
class RunHealthEfficiencyClaim:
    direction: str
    baseline_ref: str
    evaluator_ref: str


@dataclass(frozen=True)
class RunHealthInput:
    run_id: str
    owner: str
    observed_at_ms: int
    events: tuple[RunHealthEvent, ...]
    efficiency_claim: RunHealthEfficiencyClaim
    critical_path_health: dict[str, object] | None = None


def unphased_normalized_events() -> tuple[str, ...]:
    """Normalized vocabulary words this module places nowhere in the run.

    Exists so adding a word to `NORMALIZED_PROGRESS_EVENT_TYPES` without giving
    it a phase fails a test instead of silently becoming invisible to every
    phase duration, retry count, and completeness count here. The only correct
    answer is `unmapped_source_event`.
    """
    return tuple(sorted(set(NORMALIZED_PROGRESS_EVENT_TYPES) - set(_PHASE_BY_NORMALIZED_EVENT)))


def parse_run_health_input(raw: object) -> RunHealthInput:
    """Parse a `run_health_input/v1` or `run_health_input/v2` payload, or raise `ValueError`.

    The AC3 gate lives here as well as in the validator: a comparative
    `direction` without both a named baseline and a named evaluator is refused
    before a summary exists, so there is no code path that builds one.

    v1 is frozen by its exact key set, so the optional committed
    `critical_path_health/v1` section is admitted only by v2. A v2 input
    without the section parses to the same input v1 would, byte for byte.
    """
    if not isinstance(raw, dict):
        raise ValueError("run health input must use the exact run_health_input/v1 fields")
    version = raw.get("schema_version")
    critical_path_health: dict[str, object] | None = None
    if version == RUN_HEALTH_INPUT_V2_SCHEMA_VERSION:
        if set(raw) - _INPUT_V2_KEYS or _INPUT_KEYS - set(raw):
            raise ValueError("run health input must use the exact run_health_input/v2 fields")
        section = raw.get("critical_path_health")
        if section is not None:
            critical_path_health = parse_committed_critical_path_health(section)
    elif set(raw) != _INPUT_KEYS:
        raise ValueError("run health input must use the exact run_health_input/v1 fields")
    if version not in (RUN_HEALTH_INPUT_SCHEMA_VERSION, RUN_HEALTH_INPUT_V2_SCHEMA_VERSION):
        raise ValueError("unsupported run health input schema")
    run_id = _required_run_id(raw.get("run_id"))
    owner = require_opaque_metadata_ref(raw.get("owner"), field="owner")
    observed_at_ms = _nonnegative_int(raw.get("observed_at_ms"), "observed_at_ms")
    events = _parse_events(raw.get("events"))
    latest = _latest_event_clock(events)
    if latest is not None and observed_at_ms < latest:
        raise ValueError("observed_at_ms must not precede the last observed event timestamp")
    claim = _parse_efficiency_claim(raw.get("efficiency_claim"))
    return RunHealthInput(run_id, owner, observed_at_ms, events, claim, critical_path_health)


def build_run_health_summary(value: RunHealthInput) -> dict[str, object]:
    """Project one `run_health_summary/v1` (or `v2`) record. Pure: no clock, no I/O.

    A committed critical-path section upgrades the record to
    `run_health_summary/v2`; without one, the v1 bytes are produced exactly.
    """
    attribution = owner_attribution(value.owner)
    observations = tuple(
        {
            "normalized_event": str(
                normalize_owner_progress_event(value.owner, event.source_event)["normalized_event"]
            ),
            "at_ms": event.at_ms,
        }
        for event in value.events
    )
    metrics = _derive_metrics(observations, observed_at_ms=value.observed_at_ms)
    summary: dict[str, object] = {
        "schema_version": RUN_HEALTH_SUMMARY_SCHEMA_VERSION,
        "run_id": value.run_id,
        "owner_attribution": attribution,
        "observed_at_ms": value.observed_at_ms,
        "observations": [dict(observation) for observation in observations],
        "metrics": metrics,
        "staleness": derive_staleness(metrics["idle_duration_ms"]),
        "staleness_threshold_ms": RUN_HEALTH_STALENESS_THRESHOLD_MS,
        "efficiency_claim": {
            "direction": value.efficiency_claim.direction,
            "baseline_ref": value.efficiency_claim.baseline_ref,
            "evaluator_ref": value.efficiency_claim.evaluator_ref,
            "gate": efficiency_claim_gate(
                baseline_ref=value.efficiency_claim.baseline_ref,
                evaluator_ref=value.efficiency_claim.evaluator_ref,
            ),
        },
        "health_digest": "",
        "claim_boundary": RUN_HEALTH_CLAIM_BOUNDARY,
    }
    if value.critical_path_health is not None:
        summary["schema_version"] = RUN_HEALTH_SUMMARY_V2_SCHEMA_VERSION
        summary["critical_path_health"] = dict(value.critical_path_health)
    summary["health_digest"] = run_health_digest(summary)
    return summary


def owner_attribution(owner: str) -> dict[str, object]:
    """Fold the owner name and record what its stream can carry.

    Derived through `normalize_owner_progress_event` with no source word so the
    alias folding and the `owner_supported` verdict come from the normalization
    module rather than from a second copy of its owner table here.
    """
    probe = normalize_owner_progress_event(owner, "")
    label = str(probe["owner"])
    return {
        "owner": label,
        "owner_supported": bool(probe["owner_supported"]),
        "evidence_ceiling": owner_evidence_ceiling(label),
    }


def efficiency_claim_gate(*, baseline_ref: str, evaluator_ref: str) -> str:
    """Derived, never declared: both refs named, or the gate is shut."""
    if baseline_ref and evaluator_ref:
        return "named_baseline_and_evaluator"
    return "no_named_baseline_and_evaluator"


def derive_staleness(idle_metric: Mapping[str, Any]) -> str:
    """The freshness verdict, carried over from the idle metric's own state."""
    state = idle_metric.get("state")
    value = idle_metric.get("value")
    if state == "unavailable":
        return "unavailable"
    if state != "observed" or not isinstance(value, int) or isinstance(value, bool):
        return "unknown"
    return "stale" if value > RUN_HEALTH_STALENESS_THRESHOLD_MS else "fresh"


def run_health_digest(payload: Mapping[str, Any]) -> str:
    """Fingerprint the owner-independent, now-independent health facts."""
    seed = {key: value for key, value in payload.items() if key not in _DIGEST_EXCLUDED_TOP_LEVEL}
    metrics = seed.get("metrics")
    if isinstance(metrics, dict):
        seed["metrics"] = {key: value for key, value in metrics.items() if key not in _DIGEST_EXCLUDED_METRICS}
    encoded = json.dumps(seed, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


def validate_run_health_summary(payload: object) -> list[str]:
    """Every reason this payload is not a `run_health_summary/v1` or `v2` record.

    Checks the key set in both directions and re-derives everything derivable,
    so a record whose numbers were edited to read healthier is refused rather
    than rendered. The committed critical-path section is validated against
    its own schema (see `run_health_critical_path`); it is not re-derived from
    observations because the events that produced it are not carried here.
    """
    if not isinstance(payload, dict):
        return ["run_health_summary must be an object"]
    v2 = payload.get("schema_version") == RUN_HEALTH_SUMMARY_V2_SCHEMA_VERSION
    key_errors = _key_set_errors(payload, _SUMMARY_V2_KEYS if v2 else _SUMMARY_KEYS, "run_health_summary")
    if key_errors:
        return key_errors

    errors: list[str] = []
    if v2:
        errors.extend(
            committed_critical_path_health_errors(
                payload.get("critical_path_health"), "run_health_summary.critical_path_health"
            )
        )
    elif payload.get("schema_version") != RUN_HEALTH_SUMMARY_SCHEMA_VERSION:
        errors.append("run_health_summary.schema_version must be run_health_summary/v1 or run_health_summary/v2")
    if payload.get("claim_boundary") != RUN_HEALTH_CLAIM_BOUNDARY:
        errors.append("run_health_summary.claim_boundary must be the declared boundary text")
    if payload.get("staleness_threshold_ms") != RUN_HEALTH_STALENESS_THRESHOLD_MS:
        errors.append("run_health_summary.staleness_threshold_ms must match the declared threshold")
    if not _is_run_id(payload.get("run_id")):
        errors.append("run_health_summary.run_id must contain 1 to 120 safe identifier characters")

    errors.extend(_attribution_errors(payload.get("owner_attribution")))

    observed_at_ms = payload.get("observed_at_ms")
    if not _is_nonnegative_int(observed_at_ms):
        errors.append("run_health_summary.observed_at_ms must be a nonnegative integer")
        observed_at_ms = None

    observations, observation_errors = _read_observations(payload.get("observations"))
    errors.extend(observation_errors)

    metric_shape_errors = _metric_shape_errors(payload.get("metrics"))
    errors.extend(metric_shape_errors)
    errors.extend(_efficiency_claim_errors(payload.get("efficiency_claim")))

    if observations is not None and isinstance(observed_at_ms, int):
        latest = _latest_observation_clock(observations)
        if latest is not None and observed_at_ms < latest:
            errors.append("run_health_summary.observed_at_ms must not precede the last observed event timestamp")
        if not metric_shape_errors:
            errors.extend(_rederivation_errors(payload, observations, observed_at_ms))

    if payload.get("health_digest") != run_health_digest(payload):
        errors.append("run_health_summary.health_digest must match the derived health digest")
    return errors


def render_run_health_summary_text(payload: Mapping[str, Any]) -> str:
    """Plain-language rendering of one summary; the default CLI output.

    Absent metrics render as the state word plus its reason, never as a number
    and never as a blank, so a reader of the text surface learns the same three
    absences the JSON surface carries.
    """
    metrics = payload.get("metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    attribution = payload.get("owner_attribution")
    attribution = attribution if isinstance(attribution, dict) else {}
    claim = payload.get("efficiency_claim")
    claim = claim if isinstance(claim, dict) else {}
    observations = payload.get("observations")
    observations = observations if isinstance(observations, list) else []

    lane = "yes" if attribution.get("owner_supported") else "no"
    lines = [
        "Run health summary (OMH projection)",
        f"Run: {payload.get('run_id', '')}",
        f"Owner: {attribution.get('owner', '')} (progress lane: {lane}, "
        f"evidence ceiling: {attribution.get('evidence_ceiling', '')})",
        f"Observed events: {len(observations)} (observed at {payload.get('observed_at_ms', '')} ms)",
        f"Freshness: {payload.get('staleness', '')} "
        f"(idle {_metric_text(metrics.get('idle_duration_ms'), unit='ms')}, "
        f"stale after {payload.get('staleness_threshold_ms', '')} ms)",
        f"Failure class: {_metric_text(metrics.get('failure_class'))}",
        f"Total duration: {_metric_text(metrics.get('total_duration_ms'), unit='ms')}",
        "Phase durations:",
    ]
    for phase in RUN_HEALTH_PHASES:
        metric_name = _PHASE_DURATION_METRIC.get(phase)
        if metric_name is None:
            continue
        label = metric_name.removesuffix("_phase_duration_ms")
        lines.append(f"- {label}: {_metric_text(metrics.get(metric_name), unit='ms')}")
    lines.append("Counts:")
    lines.append(f"- retries: {_metric_text(metrics.get('retry_count'))}")
    lines.append(f"- evidence gaps: {_metric_text(metrics.get('evidence_gap_count'))}")
    lines.append(f"- unobserved phases: {_metric_text(metrics.get('unobserved_phase_count'))}")
    critical_path = payload.get("critical_path_health")
    if isinstance(critical_path, Mapping):
        lines.extend(render_critical_path_health_lines(critical_path))
    lines.append(
        f"Efficiency claim: {claim.get('direction', '')} "
        f"(baseline: {claim.get('baseline_ref', '') or 'none'}, "
        f"evaluator: {claim.get('evaluator_ref', '') or 'none'}, gate: {claim.get('gate', '')})"
    )
    lines.append(f"Boundary: {payload.get('claim_boundary', '')}")
    lines.append("For machine-readable output, rerun with `--json`.")
    return "\n".join(lines)


def _metric_text(metric: object, *, unit: str = "") -> str:
    """One metric as a person reads it: a number with its unit, or the absence and why."""
    if not isinstance(metric, Mapping):
        return "unknown"
    if metric.get("state") != "observed":
        return f"{metric.get('state', 'unknown')} ({metric.get('reason', '')})"
    value = str(metric.get("value"))
    return f"{value} {unit}" if unit else value


def _observed_metric(value: int | str) -> dict[str, object]:
    return {"state": "observed", "value": value, "reason": ""}


def _unknown_metric(reason: str) -> dict[str, object]:
    return {"state": "unknown", "value": None, "reason": reason}


def _unavailable_metric(reason: str) -> dict[str, object]:
    return {"state": "unavailable", "value": None, "reason": reason}


def _derive_metrics(
    observations: Sequence[Mapping[str, Any]],
    *,
    observed_at_ms: int,
) -> dict[str, object]:
    """Every metric, from the normalized observations and nothing else.

    With nothing observed, every metric is `unknown`. Reporting `0` retries or
    `0` evidence gaps for a run nobody watched would read as an observation that
    the run had none.
    """
    if not observations:
        return {name: _unknown_metric("no_observed_events") for name in RUN_HEALTH_METRICS}
    metrics: dict[str, object] = {
        "total_duration_ms": _total_duration(observations),
        "idle_duration_ms": _idle_duration(observations, observed_at_ms=observed_at_ms),
        "retry_count": _observed_metric(_retry_count(observations)),
        "evidence_gap_count": _observed_metric(_evidence_gap_count(observations)),
        "unobserved_phase_count": _observed_metric(_unobserved_phase_count(observations)),
        "failure_class": _observed_metric(_failure_class(observations)),
    }
    for phase, metric_name in _PHASE_DURATION_METRIC.items():
        metrics[metric_name] = _phase_duration(observations, phase)
    return {name: metrics[name] for name in RUN_HEALTH_METRICS}


def _total_duration(observations: Sequence[Mapping[str, Any]]) -> dict[str, object]:
    if len(observations) < 2:
        return _unknown_metric("fewer_than_two_observed_events")
    return _span(observations[0].get("at_ms"), observations[-1].get("at_ms"))


def _idle_duration(observations: Sequence[Mapping[str, Any]], *, observed_at_ms: int) -> dict[str, object]:
    last = observations[-1].get("at_ms")
    if not _is_nonnegative_int(last):
        return _unavailable_metric("boundary_event_carried_no_timestamp")
    if observed_at_ms < int(last):
        return _unknown_metric("observed_at_ms_precedes_the_last_observed_event")
    return _observed_metric(observed_at_ms - int(last))


def _phase_duration(observations: Sequence[Mapping[str, Any]], phase: str) -> dict[str, object]:
    """From the first event at this phase to the first LATER-phase event after it.

    An unclosed phase stays `unknown`. Closing it with `observed_at_ms` or with
    the last observed event would answer "how long did this phase take" with a
    number nobody observed.
    """
    rank = RUN_HEALTH_PHASES.index(phase)
    opened_at: int | None = None
    opened_index: int | None = None
    for index, observation in enumerate(observations):
        if _phase_rank(observation) == rank:
            opened_index = index
            opened_at = observation.get("at_ms") if _is_nonnegative_int(observation.get("at_ms")) else None
            break
    if opened_index is None:
        return _unknown_metric("phase_not_observed")
    for observation in observations[opened_index + 1 :]:
        observed_rank = _phase_rank(observation)
        if observed_rank is not None and observed_rank > rank:
            return _span(opened_at, observation.get("at_ms"))
    return _unknown_metric("phase_not_closed_by_a_later_observed_phase")


def _span(start: object, end: object) -> dict[str, object]:
    if not _is_nonnegative_int(start) or not _is_nonnegative_int(end):
        return _unavailable_metric("boundary_event_carried_no_timestamp")
    return _observed_metric(int(end) - int(start))


def _retry_count(observations: Sequence[Mapping[str, Any]]) -> int:
    """Events that move the run backwards through the phase order.

    A `tests_started` after a `tests_failed` is the canonical case; so is a
    `diff_started` after the executor already reported completion.
    """
    furthest = -1
    retries = 0
    for observation in observations:
        rank = _phase_rank(observation)
        if rank is None:
            continue
        if rank < furthest:
            retries += 1
        else:
            furthest = rank
    return retries


def _evidence_gap_count(observations: Sequence[Mapping[str, Any]]) -> int:
    return sum(1 for observation in observations if observation.get("normalized_event") == UNMAPPED_NORMALIZED_EVENT)


def _unobserved_phase_count(observations: Sequence[Mapping[str, Any]]) -> int:
    observed = {_phase_rank(observation) for observation in observations}
    return sum(1 for rank in range(len(RUN_HEALTH_PHASES)) if rank not in observed)


def _failure_class(observations: Sequence[Mapping[str, Any]]) -> str:
    worst = "no_failure_observed"
    for observation in observations:
        candidate = _FAILURE_CLASS_BY_NORMALIZED_EVENT.get(str(observation.get("normalized_event")))
        if candidate is None:
            continue
        if RUN_HEALTH_FAILURE_CLASSES.index(candidate) > RUN_HEALTH_FAILURE_CLASSES.index(worst):
            worst = candidate
    return worst


def _phase_rank(observation: Mapping[str, Any]) -> int | None:
    phase = _PHASE_BY_NORMALIZED_EVENT.get(str(observation.get("normalized_event")))
    if phase is None:
        return None
    return RUN_HEALTH_PHASES.index(phase)


def _parse_events(raw: object) -> tuple[RunHealthEvent, ...]:
    if not isinstance(raw, list):
        raise ValueError("run health events must be a list")
    if len(raw) > MAX_RUN_HEALTH_EVENTS:
        raise ValueError(f"run health events must contain at most {MAX_RUN_HEALTH_EVENTS} items")
    events: list[RunHealthEvent] = []
    previous: int | None = None
    for item in raw:
        if not isinstance(item, dict) or set(item) != _INPUT_EVENT_KEYS:
            raise ValueError("run health event must use exactly source_event and at_ms")
        source_event = require_opaque_metadata_ref(item.get("source_event"), field="run health event source_event")
        at_ms = item.get("at_ms")
        if at_ms is not None:
            if not _is_nonnegative_int(at_ms):
                raise ValueError("run health event at_ms must be a nonnegative integer or null")
            if previous is not None and int(at_ms) < previous:
                raise ValueError("run health event timestamps must not move backwards")
            previous = int(at_ms)
        events.append(RunHealthEvent(source_event, None if at_ms is None else int(at_ms)))
    return tuple(events)


def _parse_efficiency_claim(raw: object) -> RunHealthEfficiencyClaim:
    if not isinstance(raw, dict) or set(raw) != _INPUT_CLAIM_KEYS:
        raise ValueError("efficiency_claim must use exactly direction, baseline_ref, and evaluator_ref")
    direction = raw.get("direction")
    if direction not in RUN_HEALTH_EFFICIENCY_DIRECTIONS:
        raise ValueError("efficiency_claim.direction is unsupported")
    baseline_ref = _optional_ref(raw.get("baseline_ref"), "efficiency_claim.baseline_ref")
    evaluator_ref = _optional_ref(raw.get("evaluator_ref"), "efficiency_claim.evaluator_ref")
    if direction != "unclaimed" and not (baseline_ref and evaluator_ref):
        raise ValueError(
            "efficiency_claim.direction other than unclaimed requires a named baseline_ref and evaluator_ref"
        )
    return RunHealthEfficiencyClaim(str(direction), baseline_ref, evaluator_ref)


def _optional_ref(value: object, field: str) -> str:
    if value == "":
        return ""
    if not isinstance(value, str) or len(value) > MAX_RUN_HEALTH_REF_CHARS:
        raise ValueError(f"{field} must be an empty string or a bounded opaque reference")
    return require_opaque_metadata_ref(value, field=field)


def _latest_event_clock(events: Sequence[RunHealthEvent]) -> int | None:
    clocks = [event.at_ms for event in events if event.at_ms is not None]
    return max(clocks) if clocks else None


def _latest_observation_clock(observations: Sequence[Mapping[str, Any]]) -> int | None:
    clocks = [
        int(observation["at_ms"]) for observation in observations if _is_nonnegative_int(observation.get("at_ms"))
    ]
    return max(clocks) if clocks else None


def _read_observations(raw: object) -> tuple[list[dict[str, Any]] | None, list[str]]:
    label = "run_health_summary.observations"
    if not isinstance(raw, list):
        return None, [f"{label} must be a list"]
    if len(raw) > MAX_RUN_HEALTH_EVENTS:
        return None, [f"{label} must contain at most {MAX_RUN_HEALTH_EVENTS} items"]
    errors: list[str] = []
    observations: list[dict[str, Any]] = []
    previous: int | None = None
    for index, item in enumerate(raw):
        item_label = f"{label}[{index}]"
        if not isinstance(item, dict) or set(item) != _OBSERVATION_KEYS:
            errors.append(f"{item_label} must use exactly normalized_event and at_ms")
            continue
        if item.get("normalized_event") not in NORMALIZED_PROGRESS_EVENT_TYPES:
            errors.append(f"{item_label}.normalized_event is not in the normalized progress vocabulary")
        at_ms = item.get("at_ms")
        if at_ms is not None:
            if not _is_nonnegative_int(at_ms):
                errors.append(f"{item_label}.at_ms must be a nonnegative integer or null")
            else:
                if previous is not None and int(at_ms) < previous:
                    errors.append(f"{item_label}.at_ms must not move backwards")
                previous = int(at_ms)
        observations.append(dict(item))
    if errors:
        return None, errors
    return observations, errors


def _attribution_errors(raw: object) -> list[str]:
    label = "run_health_summary.owner_attribution"
    if not isinstance(raw, dict):
        return [f"{label} must be an object"]
    key_errors = _key_set_errors(raw, _ATTRIBUTION_KEYS, label)
    if key_errors:
        return key_errors
    owner = raw.get("owner")
    if not isinstance(owner, str) or not owner:
        return [f"{label}.owner must be a non-empty string"]
    derived = owner_attribution(owner)
    errors: list[str] = []
    if derived["owner"] != owner:
        errors.append(f"{label}.owner must already be the folded owner label")
    if raw.get("owner_supported") is not derived["owner_supported"]:
        errors.append(f"{label}.owner_supported must match the derived progress-lane verdict")
    if raw.get("evidence_ceiling") != derived["evidence_ceiling"]:
        errors.append(f"{label}.evidence_ceiling must match the owner's declared evidence ceiling")
    return errors


def _metric_shape_errors(raw: object) -> list[str]:
    label = "run_health_summary.metrics"
    if not isinstance(raw, dict):
        return [f"{label} must be an object"]
    key_errors = _key_set_errors(raw, frozenset(RUN_HEALTH_METRICS), label)
    if key_errors:
        return key_errors
    errors: list[str] = []
    for name in RUN_HEALTH_METRICS:
        errors.extend(_single_metric_errors(raw.get(name), f"{label}.{name}", RUN_HEALTH_METRIC_KINDS[name]))
    return errors


def _single_metric_errors(raw: object, label: str, kind: str) -> list[str]:
    if not isinstance(raw, dict):
        return [f"{label} must be an object"]
    key_errors = _key_set_errors(raw, _METRIC_KEYS, label)
    if key_errors:
        return key_errors
    state = raw.get("state")
    reason = raw.get("reason")
    value = raw.get("value")
    errors: list[str] = []
    if state not in RUN_HEALTH_METRIC_STATES:
        return [f"{label}.state must be one of {', '.join(RUN_HEALTH_METRIC_STATES)}"]
    if state == "observed":
        if reason != "":
            errors.append(f"{label}.reason must be empty when the metric is observed")
        errors.extend(_metric_value_errors(value, label, kind))
    else:
        if value is not None:
            errors.append(f"{label}.value must be null unless the metric is observed")
        allowed = _UNKNOWN_REASONS if state == "unknown" else _UNAVAILABLE_REASONS
        if reason not in allowed:
            errors.append(f"{label}.reason is not a declared {state} reason")
    return errors


def _metric_value_errors(value: object, label: str, kind: str) -> list[str]:
    if kind == "failure_class":
        if value not in RUN_HEALTH_FAILURE_CLASSES:
            return [f"{label}.value must be a declared failure class"]
        return []
    if not _is_nonnegative_int(value):
        return [f"{label}.value must be a nonnegative integer"]
    return []


def _efficiency_claim_errors(raw: object) -> list[str]:
    label = "run_health_summary.efficiency_claim"
    if not isinstance(raw, dict):
        return [f"{label} must be an object"]
    key_errors = _key_set_errors(raw, _SUMMARY_CLAIM_KEYS, label)
    if key_errors:
        return key_errors
    errors: list[str] = []
    direction = raw.get("direction")
    baseline_ref = raw.get("baseline_ref")
    evaluator_ref = raw.get("evaluator_ref")
    if direction not in RUN_HEALTH_EFFICIENCY_DIRECTIONS:
        errors.append(f"{label}.direction is unsupported")
    for field, value in (("baseline_ref", baseline_ref), ("evaluator_ref", evaluator_ref)):
        if not isinstance(value, str) or len(value) > MAX_RUN_HEALTH_REF_CHARS:
            errors.append(f"{label}.{field} must be a bounded string")
        elif value and not _is_opaque_ref(value):
            errors.append(f"{label}.{field} must be a safe opaque metadata reference")
    if not isinstance(baseline_ref, str) or not isinstance(evaluator_ref, str):
        return errors
    gate = efficiency_claim_gate(baseline_ref=baseline_ref, evaluator_ref=evaluator_ref)
    if raw.get("gate") != gate:
        errors.append(f"{label}.gate must be derived from baseline_ref and evaluator_ref")
    if direction in RUN_HEALTH_EFFICIENCY_DIRECTIONS and direction != "unclaimed" and gate != "named_baseline_and_evaluator":
        errors.append(f"{label}.direction other than unclaimed requires a named baseline_ref and evaluator_ref")
    return errors


def _rederivation_errors(
    payload: Mapping[str, Any],
    observations: Sequence[Mapping[str, Any]],
    observed_at_ms: int,
) -> list[str]:
    derived = _derive_metrics(observations, observed_at_ms=observed_at_ms)
    errors: list[str] = []
    stored = payload.get("metrics")
    if isinstance(stored, dict):
        for name in RUN_HEALTH_METRICS:
            if stored.get(name) != derived[name]:
                errors.append(f"run_health_summary.metrics.{name} must match the value derived from observations")
    if payload.get("staleness") != derive_staleness(derived["idle_duration_ms"]):
        errors.append("run_health_summary.staleness must match the verdict derived from idle_duration_ms")
    return errors


def _key_set_errors(payload: Mapping[str, Any], allowed: frozenset[str], label: str) -> list[str]:
    errors = [f"{label} has an unsupported key: {key}" for key in sorted(set(payload) - allowed)]
    errors.extend(f"{label} is missing a required key: {key}" for key in sorted(allowed - set(payload)))
    return errors


def _required_run_id(value: object) -> str:
    if not _is_run_id(value):
        raise ValueError("run_id must contain 1 to 120 safe identifier characters")
    return require_opaque_metadata_ref(value, field="run_id")


def _is_run_id(value: object) -> bool:
    return isinstance(value, str) and bool(_RUN_ID.fullmatch(value)) and _is_opaque_ref(value)


def _is_opaque_ref(value: object) -> bool:
    try:
        require_opaque_metadata_ref(value, field="reference")
    except ValueError:
        return False
    return True


def _is_nonnegative_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _nonnegative_int(value: object, field: str) -> int:
    if not _is_nonnegative_int(value):
        raise ValueError(f"{field} must be a nonnegative integer")
    return int(value)
