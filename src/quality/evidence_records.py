"""Deterministic, source-bound quality evidence records.

The module deliberately deals in metadata only.  It never runs a command or
upgrades a supplied assertion into observed execution evidence.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

from ..local_store import read_json_object_result

QUALITY_EVIDENCE_PACKAGE_SCHEMA = "quality_evidence_package/v1"
QUALITY_EVIDENCE_OBSERVATION_SCHEMA = "quality_evidence_observation/v1"
QUALITY_EVIDENCE_ASSESSMENT_SCHEMA = "quality_evidence_assessment/v1"
PREPARED_NOT_OBSERVED = "prepared_not_observed"
PROVENANCES = frozenset({"omh_observed_record", "supplied_unverified"})
EVIDENCE_KINDS = frozenset({"test", "visual", "performance", "review", "ci", "pr"})
RESULTS = frozenset({"passed", "failed", "unknown"})
DIMENSION_STATES = frozenset({"satisfied", "unsatisfied", "unknown", "not_applicable"})
_PACKAGE_FIELDS = frozenset({"schema_version", "status", "subject", "qa_scenarios", "review_requirements", "claim_requirements", "self_critique_questions", "claim_boundary"})


def source_identity(repository_id: str, commit_sha: str, tree_sha: str) -> dict[str, str]:
    """Return the canonical identity used for every package and observation."""
    values = (repository_id, commit_sha, tree_sha)
    if not all(isinstance(value, str) and value.strip() for value in values):
        raise ValueError("repository_id, commit_sha, and tree_sha are required")
    return {"repository_id": repository_id, "commit_sha": commit_sha, "tree_sha": tree_sha}


def build_quality_evidence_package(
    *,
    repository_id: str,
    commit_sha: str,
    tree_sha: str,
    title: str,
    executor_target: str,
    scenarios: Sequence[Mapping[str, object]] = (),
    review_requirements: Sequence[Mapping[str, object]] = (),
    claim_requirements: Sequence[Mapping[str, object]] = (),
    self_critique_questions: Sequence[str] = (),
) -> dict[str, object]:
    """Prepare a compact package; preparation is never observed evidence."""
    identity = source_identity(repository_id, commit_sha, tree_sha)
    normalized_scenarios = _with_deterministic_ids(scenarios, "scenario")
    normalized_reviews = _with_deterministic_ids(review_requirements, "review")
    normalized_claims = _with_deterministic_ids(claim_requirements, "claim")
    package = {
        "schema_version": QUALITY_EVIDENCE_PACKAGE_SCHEMA,
        "status": PREPARED_NOT_OBSERVED,
        "subject": {"title": title, "executor_target": executor_target, "source": identity},
        "qa_scenarios": normalized_scenarios,
        "review_requirements": normalized_reviews,
        "claim_requirements": normalized_claims,
        "self_critique_questions": list(self_critique_questions),
        "claim_boundary": "Prepared quality requirements are not observed QA, review, CI, PR, merge-readiness, or completion evidence.",
    }
    errors = validate_quality_evidence_package(package)
    if errors:
        raise ValueError("invalid quality evidence package: " + ", ".join(errors))
    return package


def validate_quality_evidence_package(package: Mapping[str, object]) -> list[str]:
    """Validate prepared-record shape without treating it as observed work."""
    errors: list[str] = []
    if not isinstance(package, Mapping):
        return ["invalid_package"]
    if set(package) != _PACKAGE_FIELDS:
        errors.append("invalid_top_level_fields")
    if package.get("schema_version") != QUALITY_EVIDENCE_PACKAGE_SCHEMA:
        errors.append("unknown_schema")
    if package.get("status") != PREPARED_NOT_OBSERVED:
        errors.append("invalid_prepared_status")
    subject = package.get("subject")
    if (
        not isinstance(subject, Mapping)
        or not isinstance(subject.get("title"), str)
        or not subject["title"].strip()
        or not isinstance(subject.get("executor_target"), str)
        or not subject["executor_target"].strip()
    ):
        errors.append("invalid_subject")
    try:
        _source_from_package(package)
    except ValueError:
        errors.append("invalid_source_identity")
    for field in ("qa_scenarios", "review_requirements", "claim_requirements", "self_critique_questions"):
        if not isinstance(package.get(field), list):
            errors.append(f"invalid_{field}")
    if not isinstance(package.get("claim_boundary"), str) or not package.get("claim_boundary", "").strip():
        errors.append("missing_claim_boundary")
    questions = package.get("self_critique_questions", [])
    if isinstance(questions, list) and any(not isinstance(item, str) or not item.strip() for item in questions):
        errors.append("invalid_self_critique_questions")
    for field in ("qa_scenarios", "review_requirements", "claim_requirements"):
        values = package.get(field, [])
        if not isinstance(values, list):
            continue
        ids = [str(item.get("id")) for item in values if isinstance(item, Mapping) and item.get("id")]
        if len(ids) != len(set(ids)):
            errors.append(f"duplicate_{field}_id")
        if len(ids) != len(values):
            errors.append(f"missing_{field}_id")
    return list(dict.fromkeys(errors))


def build_quality_evidence_observation(
    package: Mapping[str, object], *, evidence_id: str, evidence_kind: str, result: str,
    reference: str, observed_at: str, reporter: str, provenance: str = "supplied_unverified",
    record_ref: str | None = None, scenario_ids: Sequence[str] = (),
    review_requirement_ids: Sequence[str] = (), claim_ids: Sequence[str] = (), independence: str | None = None,
) -> dict[str, object]:
    """Build an observation bound to the package's canonical source identity."""
    observation = {"schema_version": QUALITY_EVIDENCE_OBSERVATION_SCHEMA, "evidence_id": evidence_id,
        "evidence_kind": evidence_kind, "result": result, "reference": reference,
        "observed_at": observed_at, "reporter": reporter, "source": _source_from_package(package),
        "provenance": provenance, "record_ref": record_ref, "scenario_ids": list(scenario_ids),
        "review_requirement_ids": list(review_requirement_ids), "claim_ids": list(claim_ids)}
    if independence is not None:
        observation["independence"] = independence
    errors = validate_quality_evidence_observation(observation, package)
    if errors:
        raise ValueError("invalid quality evidence observation: " + ", ".join(errors))
    return observation


def validate_quality_evidence_observation(
    observation: Mapping[str, object],
    package: Mapping[str, object],
) -> list[str]:
    """Return deterministic reason codes; no external work is performed."""
    if not isinstance(observation, Mapping):
        return ["invalid_observation"]
    errors: list[str] = []
    if observation.get("schema_version") != QUALITY_EVIDENCE_OBSERVATION_SCHEMA:
        errors.append("unknown_schema")
    kind = observation.get("evidence_kind")
    if kind not in EVIDENCE_KINDS:
        errors.append("invalid_evidence_kind")
    if observation.get("result") not in RESULTS:
        errors.append("invalid_result")
    provenance = observation.get("provenance")
    if provenance not in PROVENANCES:
        errors.append("unknown_provenance")
    source = _source_from_package(package)
    observed_source = observation.get("source")
    if not isinstance(observed_source, Mapping) or dict(observed_source) != source:
        errors.append("source_mismatch")
    if not str(observation.get("evidence_id") or "").strip():
        errors.append("missing_evidence_id")
    if not isinstance(observation.get("reporter"), str) or not observation.get("reporter", "").strip():
        errors.append("missing_reporter")
    if not str(observation.get("reference") or "").strip():
        errors.append("missing_reference")
    if not _parse_timestamp(observation.get("observed_at")):
        errors.append("missing_or_invalid_observed_at")
    if provenance == "omh_observed_record" and not str(observation.get("record_ref") or "").strip():
        errors.append("missing_observed_record_ref")
    if kind == "review" and observation.get("independence") not in {"independent", "self_review_only"}:
        errors.append("missing_review_independence")
    valid_ids = _package_ids(package)
    for field in ("scenario_ids", "review_requirement_ids", "claim_ids"):
        values = observation.get(field, [])
        if not isinstance(values, (list, tuple)):
            errors.append("invalid_requirement_ids")
            continue
        if any(item not in valid_ids[field] for item in values):
            errors.append("unknown_requirement_id")
    return list(dict.fromkeys(errors))


def assess_quality_evidence(
    package: Mapping[str, object], observations: Sequence[Mapping[str, object]] = (), *, now: datetime | None = None,
    omh_home: str | Path | None = None,
) -> dict[str, object]:
    """Derive independent dimensions and fail closed on drift or self-review."""
    package_errors = validate_quality_evidence_package(package)
    if package_errors:
        raise ValueError("invalid quality evidence package: " + ", ".join(package_errors))
    source = _source_from_package(package)
    valid: list[Mapping[str, object]] = []
    reasons: list[str] = []
    for item in observations:
        errors = validate_quality_evidence_observation(item, package)
        if errors:
            reasons.extend(errors)
            continue
        if item.get("independence") == "self_review_only":
            reasons.append("self_review_only_not_admissible")
            continue
        if item.get("provenance") == "omh_observed_record":
            executor_target = str(package["subject"]["executor_target"])
            if _record_is_admissible(item, source, executor_target, omh_home):
                valid.append(item)
            else:
                reasons.append("unresolved_observed_record")
        else:
            reasons.append("supplied_unverified_not_admissible")
    scenarios = _package_ids(package)["scenario_ids"]
    observed_scenarios = {sid for item in valid if item.get("result") == "passed" for sid in item.get("scenario_ids", [])}
    scenario_state = "not_applicable" if not scenarios else "satisfied" if observed_scenarios >= scenarios else "unknown" if not valid else "unsatisfied"
    if any(item.get("result") == "failed" and item.get("scenario_ids") for item in valid):
        scenario_state = "unsatisfied"
    scenario_results: dict[str, set[object]] = {}
    for item in valid:
        for scenario_id in item.get("scenario_ids", []):
            scenario_results.setdefault(str(scenario_id), set()).add(item.get("result"))
    if any(len(results) > 1 for results in scenario_results.values()):
        reasons.append("contradictory_observations")
        scenario_state = "unsatisfied"
    freshness = "satisfied" if valid and all(dict(item.get("source", {})) == source for item in valid) else "unsatisfied" if "source_mismatch" in reasons else "unknown"
    reviews = _package_ids(package)["review_requirement_ids"]
    independent = {rid for item in valid if item.get("evidence_kind") == "review" and item.get("independence") == "independent" and item.get("result") == "passed" for rid in item.get("review_requirement_ids", [])}
    review_state = "not_applicable" if not reviews else "satisfied" if independent >= reviews else "unknown" if not valid else "unsatisfied"
    ci_state, ci_items = _explicit_requirement_state(package, valid, "ci")
    pr_state, pr_items = _explicit_requirement_state(package, valid, "pr")
    claim_ids = _package_ids(package)["claim_ids"]
    observed_claims = {cid for item in valid if item.get("result") == "passed" for cid in item.get("claim_ids", [])}
    claim_state = "not_applicable" if not claim_ids else "satisfied" if observed_claims >= claim_ids else "unknown" if not valid else "unsatisfied"
    evidence_ids = {
        "scenario_coverage": [str(item["evidence_id"]) for item in valid if item.get("scenario_ids")],
        "source_freshness": [str(item["evidence_id"]) for item in valid],
        "review_independence": [str(item["evidence_id"]) for item in valid if item.get("evidence_kind") == "review" and item.get("independence") == "independent"],
        "ci_status": [str(item["evidence_id"]) for item in valid if item.get("evidence_kind") == "ci"],
        "pr_status": [str(item["evidence_id"]) for item in valid if item.get("evidence_kind") == "pr"],
        "claim_coverage": [str(item["evidence_id"]) for item in valid if item.get("claim_ids")],
    }
    states = {"scenario_coverage": scenario_state, "source_freshness": freshness, "review_independence": review_state, "ci_status": ci_state, "pr_status": pr_state, "claim_coverage": claim_state}
    dimensions = {name: _dimension(state, reasons, evidence_ids[name]) for name, state in states.items()}
    complete = all(item["status"] in {"satisfied", "not_applicable"} for item in dimensions.values())
    return {"schema_version": QUALITY_EVIDENCE_ASSESSMENT_SCHEMA, "source": source, "dimensions": dimensions, "ready_for_completion": complete, "next_action": "record_source_bound_observations" if not complete else "none", "reasons": list(dict.fromkeys(reasons)), "claim_boundary": "Assessment validates evidence consistency only; it does not prove external execution."}


def _source_from_package(package: Mapping[str, object]) -> dict[str, str]:
    subject = package.get("subject")
    source = subject.get("source") if isinstance(subject, Mapping) else None
    if not isinstance(source, Mapping):
        raise ValueError("package subject.source is required")
    repository_id = source.get("repository_id")
    commit_sha = source.get("commit_sha")
    tree_sha = source.get("tree_sha")
    if set(source) != {"repository_id", "commit_sha", "tree_sha"}:
        raise ValueError("package subject.source has invalid fields")
    if not all(isinstance(value, str) for value in (repository_id, commit_sha, tree_sha)):
        raise ValueError("package subject.source values must be strings")
    return source_identity(repository_id, commit_sha, tree_sha)


def _with_deterministic_ids(values: Sequence[Mapping[str, object]], prefix: str) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for index, item in enumerate(values, start=1):
        normalized = dict(item)
        if not str(normalized.get("id") or "").strip():
            normalized["id"] = f"{prefix}-{index}"
        result.append(normalized)
    return result


def resolve_omh_record_ref(omh_home: str | Path, record_ref: str) -> dict[str, object] | None:
    """Resolve one OMH-owned JSON record without following symlinks or escaping home."""
    if not isinstance(record_ref, str) or not record_ref.strip():
        return None
    root = Path(omh_home).expanduser().resolve()
    raw_candidate = root / record_ref.strip()
    if raw_candidate.is_symlink():
        return None
    candidate = raw_candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    record, error = read_json_object_result(candidate)
    return record if error is None and isinstance(record, dict) else None


def _record_is_admissible(
    observation: Mapping[str, object], source: Mapping[str, str], executor_target: str, omh_home: str | Path | None
) -> bool:
    if not omh_home or not isinstance(observation.get("record_ref"), str):
        return False
    record = resolve_omh_record_ref(omh_home, observation["record_ref"])
    if record is None:
        return False
    record_source = record.get("source")
    if record_source != dict(source):
        return False
    if record.get("record_type") not in {
        "quality_evidence_observation",
        "runtime_observation",
        "review",
        "ci",
        "merge",
    }:
        return False
    executor_fields = [record.get(key) for key in ("executor", "executor_target") if key in record]
    if not executor_fields or any(not isinstance(value, str) or not value.strip() or value.strip() != executor_target for value in executor_fields):
        return False
    kind = record.get("evidence_kind", record.get("kind"))
    if kind != observation.get("evidence_kind"):
        return False
    result = record.get("result", record.get("status"))
    if result != observation.get("result"):
        return False
    if record.get("observed") is not True or record.get("provenance") != "omh_observed_record":
        return False
    for key in ("evidence_id", "reference", "reporter", "observed_at", "scenario_ids", "review_requirement_ids", "claim_ids"):
        if record.get(key) != observation.get(key):
            return False
    if "independence" in observation and record.get("independence") != observation.get("independence"):
        return False
    return True


def _explicit_requirement_state(package: Mapping[str, object], valid: Sequence[Mapping[str, object]], kind: str) -> tuple[str, list[Mapping[str, object]]]:
    requirements = [item for item in package.get("review_requirements", []) if isinstance(item, Mapping) and item.get("kind") == kind]
    if not requirements:
        return "not_applicable", []
    requirement_ids = {str(item["id"]) for item in requirements if item.get("id")}
    items = [item for item in valid if item.get("evidence_kind") == kind and requirement_ids.intersection(str(value) for value in item.get("review_requirement_ids", []))]
    matching = {rid: [item for item in items if rid in {str(value) for value in item.get("review_requirement_ids", [])}] for rid in requirement_ids}
    if any(any(item.get("result") == "failed" for item in rows) for rows in matching.values()):
        return "unsatisfied", items
    if all(any(item.get("result") == "passed" for item in rows) for rows in matching.values()):
        return "satisfied", items
    return ("unsatisfied" if items else "unknown"), items


def _package_ids(package: Mapping[str, object]) -> dict[str, set[str]]:
    return {"scenario_ids": {str(item.get("id")) for item in package.get("qa_scenarios", []) if isinstance(item, Mapping) and item.get("id")}, "review_requirement_ids": {str(item.get("id")) for item in package.get("review_requirements", []) if isinstance(item, Mapping) and item.get("id")}, "claim_ids": {str(item.get("id")) for item in package.get("claim_requirements", []) if isinstance(item, Mapping) and item.get("id")}}


def _dimension(status: str, reasons: Sequence[str], evidence_ids: Sequence[str]) -> dict[str, object]:
    return {"status": status if status in DIMENSION_STATES else "unknown", "reason_codes": list(dict.fromkeys(reasons)), "evidence_ids": list(dict.fromkeys(evidence_ids))}


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
