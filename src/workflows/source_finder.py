from __future__ import annotations

import hashlib
from typing import Any, Iterable


SOURCE_FINDER_PLAN_SCHEMA_VERSION = "source_finder_plan/v1"
SOURCE_CANDIDATE_SCHEMA_VERSION = "source_candidate/v1"
SOURCE_CANDIDATE_SET_SCHEMA_VERSION = "source_candidate_set/v1"
SOURCE_ACQUISITION_STATUS_SCHEMA_VERSION = "source_acquisition_status/v1"
SOURCE_FINDER_SOURCE_KINDS = (
    "paper",
    "web_link",
    "dataset",
    "github_repo",
    "presentation",
    "docs_spec",
    "unknown",
)
SOURCE_FINDER_ACQUISITION_STATES = (
    "candidate_prepared",
    "link_observed",
    "download_link_prepared",
    "download_observed",
    "file_hash_recorded",
    "text_extraction_observed",
    "license_checked",
    "verification_observed",
    "downstream_selected",
)
_SOURCE_FINDER_PROVENANCE_REQUIRED_STATES = {
    "link_observed",
    "download_observed",
    "file_hash_recorded",
    "text_extraction_observed",
    "license_checked",
    "verification_observed",
    "downstream_selected",
}
SOURCE_FINDER_OBSERVATION_PROVENANCE = (
    "user",
    "wrapper",
    "hermes_tool",
    "local_file",
    "runtime_observation",
    "unknown",
)
SOURCE_FINDER_DOWNSTREAM_WORKFLOWS = (
    "paper-learning",
    "web-research",
    "research-brief",
    "research-department",
    "materials-package",
    "ultraprocess",
    "unknown",
)
SOURCE_FINDER_NOT_OBSERVED = (
    "web_search_execution",
    "download_execution",
    "repository_clone",
    "file_extraction",
    "file_hash_verification",
    "license_verification",
    "source_correctness_verification",
    "downstream_processing",
)
SOURCE_FINDER_ACTIONS = (
    "prepare_source_finder_plan",
    "show_source_candidates",
    "record_source_candidate",
    "record_source_link_observed",
    "record_download_observed",
    "record_file_hash",
    "record_text_extraction_observed",
    "record_license_check",
    "choose_source",
    "route_to_downstream_workflow",
    "show_acquisition_status",
    "show_status",
)
SOURCE_FINDER_PRECEDENCE = {
    "web-research": "Use for current evidence, citations, fact-finding, and source-backed synthesis.",
    "paper-learning": "Use for explanation of a supplied or already-observed paper/PDF/arXiv/DOI/excerpt.",
    "research-department": "Use for recurring source inbox, monitoring, and Scout/Analyst/Briefer operations.",
    "materials-package": "Use for file export, package, and render QA requests.",
    "img-summary": "Use for image-card or visual summary requests over selected material.",
}


def normalize_source_kind(kind: str | None) -> str:
    if not kind:
        return "unknown"
    normalized = _key(kind)
    aliases = {
        "paper": "paper",
        "papers": "paper",
        "research paper": "paper",
        "arxiv": "paper",
        "doi": "paper",
        "pdf paper": "paper",
        "논문": "paper",
        "web": "web_link",
        "web link": "web_link",
        "link": "web_link",
        "url": "web_link",
        "article": "web_link",
        "website": "web_link",
        "dataset": "dataset",
        "datasets": "dataset",
        "data": "dataset",
        "benchmark": "dataset",
        "github": "github_repo",
        "github repo": "github_repo",
        "repo": "github_repo",
        "repository": "github_repo",
        "oss": "github_repo",
        "open source": "github_repo",
        "presentation": "presentation",
        "presentations": "presentation",
        "slides": "presentation",
        "public slides": "presentation",
        "deck": "presentation",
        "ppt": "presentation",
        "keynote": "presentation",
        "docs": "docs_spec",
        "documentation": "docs_spec",
        "spec": "docs_spec",
        "specification": "docs_spec",
        "standard": "docs_spec",
        "rfc": "docs_spec",
        "unknown": "unknown",
    }
    return aliases.get(normalized, "unknown")


def normalize_acquisition_state(state: str | None, *, provenance: str | None = None) -> str:
    if not state:
        return "candidate_prepared"
    normalized = _key(state).replace(" ", "_")
    aliases = {
        "candidate": "candidate_prepared",
        "prepared": "candidate_prepared",
        "candidate_prepared": "candidate_prepared",
        "link": "link_observed",
        "url": "link_observed",
        "link_observed": "link_observed",
        "download_link": "download_link_prepared",
        "download_link_prepared": "download_link_prepared",
        "downloaded": "download_observed",
        "download_observed": "download_observed",
        "hash": "file_hash_recorded",
        "file_hash": "file_hash_recorded",
        "file_hash_recorded": "file_hash_recorded",
        "extracted": "text_extraction_observed",
        "text_extraction": "text_extraction_observed",
        "text_extraction_observed": "text_extraction_observed",
        "license": "license_checked",
        "license_checked": "license_checked",
        "verified": "verification_observed",
        "verification_observed": "verification_observed",
        "downstream": "downstream_selected",
        "downstream_selected": "downstream_selected",
    }
    normalized = aliases.get(normalized, "candidate_prepared")
    if normalized in _SOURCE_FINDER_PROVENANCE_REQUIRED_STATES and normalize_observation_provenance(provenance) == "unknown":
        return "candidate_prepared"
    return normalized


def normalize_observation_provenance(provenance: str | None) -> str:
    normalized = _key(provenance or "unknown").replace(" ", "_")
    if normalized in SOURCE_FINDER_OBSERVATION_PROVENANCE:
        return normalized
    return "unknown"


def infer_downstream_workflow(kind: str | None, *, intent: str = "") -> str:
    source_kind = normalize_source_kind(kind)
    normalized_intent = _key(intent)
    if any(token in normalized_intent for token in ("package", "export", "ppt", "pdf", "deck", "slides")):
        return "materials-package"
    if any(token in normalized_intent for token in ("monitor", "daily", "weekly", "recurring", "inbox")):
        return "research-department"
    if source_kind == "paper":
        return "paper-learning"
    if source_kind in {"web_link", "docs_spec"}:
        return "web-research"
    if source_kind in {"dataset", "github_repo"}:
        return "research-brief"
    if source_kind == "presentation":
        return "materials-package"
    return "unknown"


def build_source_candidate(
    *,
    title: str = "unknown source",
    kind: str | None = None,
    uri: str = "",
    summary: str = "",
    downstream_workflow: str | None = None,
    acquisition_state: str | None = None,
    observation_provenance: str | None = None,
    observed_at: str = "",
    evidence_uri: str = "",
    evidence_note: str = "",
    tags: Iterable[str] = (),
) -> dict[str, object]:
    source_kind = normalize_source_kind(kind)
    provenance = normalize_observation_provenance(observation_provenance)
    state = normalize_acquisition_state(acquisition_state, provenance=provenance)
    downstream = downstream_workflow or infer_downstream_workflow(source_kind, intent=summary)
    if downstream not in SOURCE_FINDER_DOWNSTREAM_WORKFLOWS:
        downstream = "unknown"
    return {
        "schema_version": SOURCE_CANDIDATE_SCHEMA_VERSION,
        "candidate_id": _candidate_id(title, uri, source_kind),
        "title": title.strip() or "unknown source",
        "kind": source_kind,
        "uri": uri.strip(),
        "summary": summary.strip(),
        "downstream_workflow": downstream,
        "acquisition_state": state,
        "observation_provenance": provenance,
        "observed_at": observed_at.strip(),
        "evidence_uri": evidence_uri.strip(),
        "evidence_note": evidence_note.strip(),
        "tags": _clean_unique(tags),
        "not_evidence_until_observed": list(SOURCE_FINDER_NOT_OBSERVED),
    }


def build_source_candidate_set(
    *,
    query: str,
    candidates: Iterable[dict[str, Any]] = (),
    desired_kinds: Iterable[str] = (),
    source_boundaries: Iterable[str] = (),
    downstream_hint: str = "",
) -> dict[str, object]:
    normalized_candidates = [_coerce_candidate(candidate) for candidate in candidates]
    return {
        "schema_version": SOURCE_CANDIDATE_SET_SCHEMA_VERSION,
        "candidate_set_id": _candidate_set_id(query, normalized_candidates),
        "query": query.strip(),
        "desired_kinds": _normalize_kinds(desired_kinds),
        "source_boundaries": _clean_unique(source_boundaries),
        "downstream_hint": downstream_hint.strip(),
        "candidates": normalized_candidates,
        "candidate_count": len(normalized_candidates),
        "not_evidence_until_observed": list(SOURCE_FINDER_NOT_OBSERVED),
    }


def build_source_acquisition_status(candidate: dict[str, Any]) -> dict[str, object]:
    normalized = _coerce_candidate(candidate)
    state = str(normalized["acquisition_state"])
    provenance = str(normalized["observation_provenance"])
    observed_states = _observed_states(state, provenance)
    missing = [state for state in SOURCE_FINDER_ACQUISITION_STATES if state not in observed_states]
    return {
        "schema_version": SOURCE_ACQUISITION_STATUS_SCHEMA_VERSION,
        "candidate_id": normalized["candidate_id"],
        "kind": normalized["kind"],
        "current_state": state,
        "observation_provenance": provenance,
        "observed_states": observed_states,
        "missing_states": missing,
        "downstream_workflow": normalized["downstream_workflow"],
        "not_evidence_until_observed": list(SOURCE_FINDER_NOT_OBSERVED),
    }


def build_source_finder_plan(
    *,
    request: str,
    desired_kinds: Iterable[str] = (),
    source_boundaries: Iterable[str] = (),
    candidates: Iterable[dict[str, Any]] = (),
    downstream_hint: str = "",
    output_language: str = "source",
) -> dict[str, object]:
    candidate_set = build_source_candidate_set(
        query=request,
        candidates=candidates,
        desired_kinds=desired_kinds,
        source_boundaries=source_boundaries,
        downstream_hint=downstream_hint,
    )
    return {
        "schema_version": SOURCE_FINDER_PLAN_SCHEMA_VERSION,
        "plan_id": _plan_id(request, candidate_set["candidate_set_id"]),
        "request": request.strip(),
        "output_language": output_language.strip() or "source",
        "source_candidate_set": candidate_set,
        "precedence": dict(SOURCE_FINDER_PRECEDENCE),
        "acquisition_states": list(SOURCE_FINDER_ACQUISITION_STATES),
        "available_actions": list(SOURCE_FINDER_ACTIONS),
        "next_actions": list(SOURCE_FINDER_ACTIONS[:6]),
        "not_evidence_until_observed": list(SOURCE_FINDER_NOT_OBSERVED),
    }


def validate_source_candidate(candidate: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if candidate.get("schema_version") != SOURCE_CANDIDATE_SCHEMA_VERSION:
        errors.append("schema_version must be source_candidate/v1")
    if candidate.get("kind") not in SOURCE_FINDER_SOURCE_KINDS:
        errors.append("kind is unsupported")
    if candidate.get("acquisition_state") not in SOURCE_FINDER_ACQUISITION_STATES:
        errors.append("acquisition_state is unsupported")
    if candidate.get("observation_provenance") not in SOURCE_FINDER_OBSERVATION_PROVENANCE:
        errors.append("observation_provenance is unsupported")
    if candidate.get("downstream_workflow") not in SOURCE_FINDER_DOWNSTREAM_WORKFLOWS:
        errors.append("downstream_workflow is unsupported")
    if not set(SOURCE_FINDER_NOT_OBSERVED).issubset(set(candidate.get("not_evidence_until_observed", []))):
        errors.append("not_evidence_until_observed must include all source-finder boundaries")
    return errors


def validate_source_candidate_set(candidate_set: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if candidate_set.get("schema_version") != SOURCE_CANDIDATE_SET_SCHEMA_VERSION:
        errors.append("schema_version must be source_candidate_set/v1")
    if not isinstance(candidate_set.get("candidates"), list):
        errors.append("candidates must be a list")
    else:
        for index, candidate in enumerate(candidate_set["candidates"]):
            for error in validate_source_candidate(candidate):
                errors.append(f"candidates[{index}]: {error}")
    if not set(SOURCE_FINDER_NOT_OBSERVED).issubset(set(candidate_set.get("not_evidence_until_observed", []))):
        errors.append("not_evidence_until_observed must include all source-finder boundaries")
    return errors


def validate_source_acquisition_status(status: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if status.get("schema_version") != SOURCE_ACQUISITION_STATUS_SCHEMA_VERSION:
        errors.append("schema_version must be source_acquisition_status/v1")
    if status.get("current_state") not in SOURCE_FINDER_ACQUISITION_STATES:
        errors.append("current_state is unsupported")
    if status.get("observation_provenance") not in SOURCE_FINDER_OBSERVATION_PROVENANCE:
        errors.append("observation_provenance is unsupported")
    if not isinstance(status.get("observed_states"), list):
        errors.append("observed_states must be a list")
    if not set(SOURCE_FINDER_NOT_OBSERVED).issubset(set(status.get("not_evidence_until_observed", []))):
        errors.append("not_evidence_until_observed must include all source-finder boundaries")
    return errors


def validate_source_finder_plan(plan: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if plan.get("schema_version") != SOURCE_FINDER_PLAN_SCHEMA_VERSION:
        errors.append("schema_version must be source_finder_plan/v1")
    candidate_set = plan.get("source_candidate_set")
    if not isinstance(candidate_set, dict):
        errors.append("source_candidate_set must be an object")
    else:
        errors.extend(validate_source_candidate_set(candidate_set))
    if not set(SOURCE_FINDER_NOT_OBSERVED).issubset(set(plan.get("not_evidence_until_observed", []))):
        errors.append("not_evidence_until_observed must include all source-finder boundaries")
    return errors


def _coerce_candidate(candidate: dict[str, Any]) -> dict[str, object]:
    return build_source_candidate(
        title=str(candidate.get("title", "unknown source")),
        kind=str(candidate.get("kind", "unknown")),
        uri=str(candidate.get("uri", "")),
        summary=str(candidate.get("summary", "")),
        downstream_workflow=str(candidate.get("downstream_workflow", "") or ""),
        acquisition_state=str(candidate.get("acquisition_state", "") or ""),
        observation_provenance=str(candidate.get("observation_provenance", "") or ""),
        observed_at=str(candidate.get("observed_at", "") or ""),
        evidence_uri=str(candidate.get("evidence_uri", "") or ""),
        evidence_note=str(candidate.get("evidence_note", "") or ""),
        tags=tuple(str(tag) for tag in candidate.get("tags", ()) if str(tag).strip())
        if isinstance(candidate.get("tags", ()), (list, tuple))
        else (),
    )


def _normalize_kinds(kinds: Iterable[str]) -> list[str]:
    normalized = [normalize_source_kind(kind) for kind in kinds]
    cleaned = [kind for kind in normalized if kind != "unknown"]
    return _clean_unique(cleaned) or ["unknown"]


def _observed_states(state: str, provenance: str) -> list[str]:
    if provenance == "unknown" or state == "candidate_prepared":
        return []
    return [state]


def _clean_unique(values: Iterable[str]) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value).strip()
        key = _key(text)
        if text and key not in seen:
            cleaned.append(text)
            seen.add(key)
    return cleaned


def _key(value: str) -> str:
    return " ".join(value.strip().lower().replace("_", " ").replace("-", " ").split())


def _candidate_id(title: str, uri: str, kind: str) -> str:
    seed = "|".join((title.strip().lower(), uri.strip().lower(), kind))
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"source-{digest}"


def _candidate_set_id(query: str, candidates: list[dict[str, object]]) -> str:
    seed = "|".join(
        [query.strip().lower(), *[str(candidate.get("candidate_id", "")) for candidate in candidates]]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"source-set-{digest}"


def _plan_id(request: str, candidate_set_id: object) -> str:
    seed = f"{request.strip().lower()}|{candidate_set_id}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"source-finder-{digest}"
