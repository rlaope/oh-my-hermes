from __future__ import annotations

import hashlib
from typing import Any, Iterable


PAPER_LEARNING_CARD_SCHEMA_VERSION = "paper_learning_card/v1"
PAPER_LEARNING_LEVELS = ("very_easy", "moderate", "expert", "choose")
PAPER_LEARNING_SOURCE_STATES = (
    "metadata_only",
    "excerpt_text_observed",
    "file_text_extraction_observed",
    "full_text_observed",
    "unknown_or_missing",
)
PAPER_LEARNING_COVERAGE_POLICY = "coverage_preserving_not_lossy_summary"
DEFAULT_PAPER_SECTIONS = (
    "Abstract",
    "Introduction",
    "Related work / prior context",
    "Method",
    "Data or experimental setup",
    "Results",
    "Figures, tables, and equations",
    "Limitations",
    "Implications",
    "Reproducibility notes",
)
PAPER_LEARNING_NOT_OBSERVED = (
    "full_pdf_extraction",
    "figure_ocr",
    "external_citation_check",
    "math_proof_validation",
    "code_or_benchmark_reproduction",
    "peer_review_or_claim_correctness",
)
PAPER_LEARNING_ACTIONS = (
    "choose_explanation_level",
    "show_paper_source_requirements",
    "record_paper_metadata",
    "record_paper_excerpt_observed",
    "record_file_text_extraction_observed",
    "show_paper_learning",
    "continue_next_section",
    "revise_explanation_level",
    "show_coverage_ledger",
    "record_user_review",
    "show_status",
)
PAPER_LEARNING_LEVEL_CONTRACT = {
    "very_easy": {
        "label": "Very easy",
        "style": "plain language, prerequisite concepts inline, glossary, analogies, and slow build-up",
        "coverage_rule": "Do not drop sections, claims, equations, figures, or limitations; simplify scaffolding only.",
    },
    "moderate": {
        "label": "Moderate",
        "style": "practitioner or graduate-friendly language with technical terms retained and explained",
        "coverage_rule": "Preserve all substantive content while balancing intuition, mechanism, and implications.",
    },
    "expert": {
        "label": "Expert",
        "style": "technical terminology, assumptions, equations, method critique, result critique, and reproducibility notes",
        "coverage_rule": "Preserve section coverage and distinguish paper claims from independently verified truth.",
    },
    "choose": {
        "label": "Choose level",
        "style": "ask the user to choose very_easy, moderate, or expert before drafting the explanation",
        "coverage_rule": "Prepare the scope and source boundary; do not guess the user's desired explanation level.",
    },
}


def normalize_paper_learning_level(level: str | None) -> str:
    """Normalize user-facing level aliases without changing explanation content."""
    if not level:
        return "choose"
    normalized = level.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "easy": "very_easy",
        "very_easy": "very_easy",
        "beginner": "very_easy",
        "plain": "very_easy",
        "쉽게": "very_easy",
        "아주_쉽게": "very_easy",
        "moderate": "moderate",
        "medium": "moderate",
        "normal": "moderate",
        "intermediate": "moderate",
        "적당한": "moderate",
        "expert": "expert",
        "advanced": "expert",
        "technical": "expert",
        "전문가급": "expert",
        "choose": "choose",
        "ask": "choose",
    }
    return aliases.get(normalized, "choose")


def normalize_paper_source_state(
    state: str | None,
    *,
    observed_sections: Iterable[str] = (),
    missing_sections: Iterable[str] = (),
    evidence_ref: str = "",
) -> dict[str, object]:
    normalized = (state or "unknown_or_missing").strip().lower()
    if normalized not in PAPER_LEARNING_SOURCE_STATES:
        normalized = "unknown_or_missing"
    observed = _clean_unique(observed_sections)
    missing = _clean_unique(missing_sections)
    if normalized == "full_text_observed" and missing:
        normalized = "file_text_extraction_observed"
    if normalized in {"metadata_only", "unknown_or_missing"} and observed:
        normalized = "excerpt_text_observed"
    return {
        "state": normalized,
        "observed_sections": observed,
        "missing_sections": missing,
        "evidence_ref": evidence_ref.strip(),
    }


def build_coverage_ledger(
    *,
    observed_sections: Iterable[str] = (),
    missing_sections: Iterable[str] = (),
    sections: Iterable[str] = DEFAULT_PAPER_SECTIONS,
) -> list[dict[str, str]]:
    observed_keys = {_key(section) for section in observed_sections}
    missing_keys = {_key(section) for section in missing_sections}
    ledger: list[dict[str, str]] = []
    for section in _clean_unique(sections) or list(DEFAULT_PAPER_SECTIONS):
        key = _key(section)
        if key in observed_keys:
            status = "observed"
            explanation_status = "pending"
        elif key in missing_keys:
            status = "missing"
            explanation_status = "pending"
        else:
            status = "prepared"
            explanation_status = "pending"
        ledger.append(
            {
                "paper_section": section,
                "status": status,
                "explanation_status": explanation_status,
            }
        )
    return ledger


def build_paper_learning_card(
    *,
    title: str = "unknown or supplied",
    authors: Iterable[str] = (),
    source_ref: str = "",
    level: str | None = "choose",
    source_state: str | None = "unknown_or_missing",
    observed_sections: Iterable[str] = (),
    missing_sections: Iterable[str] = (),
    evidence_ref: str = "",
    sections: Iterable[str] = DEFAULT_PAPER_SECTIONS,
    output_language: str = "source",
) -> dict[str, object]:
    observed = _clean_unique(observed_sections)
    missing = _clean_unique(missing_sections)
    level_id = normalize_paper_learning_level(level)
    card = {
        "schema_version": PAPER_LEARNING_CARD_SCHEMA_VERSION,
        "card_id": _card_id(title, source_ref, level_id),
        "paper_identity": {
            "title": title.strip() or "unknown or supplied",
            "authors": _clean_unique(authors),
            "source_ref": source_ref.strip(),
        },
        "source_state": normalize_paper_source_state(
            source_state,
            observed_sections=observed,
            missing_sections=missing,
            evidence_ref=evidence_ref,
        ),
        "level": level_id,
        "level_contract": PAPER_LEARNING_LEVEL_CONTRACT[level_id],
        "output_language": output_language.strip() or "source",
        "coverage_policy": PAPER_LEARNING_COVERAGE_POLICY,
        "coverage_ledger": build_coverage_ledger(
            observed_sections=observed,
            missing_sections=missing,
            sections=sections,
        ),
        "chunking_policy": {
            "mode": "section_by_section",
            "part_index": 1,
            "part_count_when_known": None,
            "chunk_stop_rule": "End each chunk with covered / next / missing; say done only when the ledger is complete.",
        },
        "explanation_outline": (
            "What problem the paper studies",
            "What the paper claims",
            "Prior work / gap",
            "Method",
            "Data or experimental setup",
            "Results",
            "Figures, tables, and equations",
            "Limitations",
            "Implications",
            "Reproducibility notes",
            "Glossary / concept ladder",
        ),
        "not_observed": list(PAPER_LEARNING_NOT_OBSERVED),
        "available_actions": list(PAPER_LEARNING_ACTIONS),
        "next_actions": list(PAPER_LEARNING_ACTIONS[:8]),
    }
    return card


def validate_paper_learning_card(card: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if card.get("schema_version") != PAPER_LEARNING_CARD_SCHEMA_VERSION:
        errors.append("schema_version must be paper_learning_card/v1")
    if card.get("level") not in PAPER_LEARNING_LEVELS:
        errors.append("level must be one of very_easy, moderate, expert, choose")
    source_state = card.get("source_state")
    if not isinstance(source_state, dict):
        errors.append("source_state must be an object")
    elif source_state.get("state") not in PAPER_LEARNING_SOURCE_STATES:
        errors.append("source_state.state is unsupported")
    if card.get("coverage_policy") != PAPER_LEARNING_COVERAGE_POLICY:
        errors.append("coverage_policy must preserve coverage")
    ledger = card.get("coverage_ledger")
    if not isinstance(ledger, list) or not ledger:
        errors.append("coverage_ledger must be a non-empty list")
    if not set(PAPER_LEARNING_NOT_OBSERVED).issubset(set(card.get("not_observed", []))):
        errors.append("not_observed must include paper extraction and validation boundaries")
    return errors


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


def _card_id(title: str, source_ref: str, level: str) -> str:
    seed = "|".join((title.strip().lower(), source_ref.strip().lower(), level))
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    return f"paper-learning-{digest}"
