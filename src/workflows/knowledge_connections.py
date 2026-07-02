from __future__ import annotations

from dataclasses import dataclass
from typing import Final, TypeAlias, assert_never


KnowledgeConnectionIntent: TypeAlias = dict[str, str | bool | list[str]]
KnowledgeStoreIntent: TypeAlias = dict[str, str | bool]

CONNECTION_INTENT_SCHEMA_VERSION: Final = "knowledge_connection_intent/v1"
CONNECTION_READINESS_SCHEMA_VERSION: Final = "knowledge_connection_readiness/v1"
STORE_INTENT_SCHEMA_VERSION: Final = "knowledge_store_intent/v1"
UNKNOWN_READINESS: Final = "unknown"
AVAILABLE_READINESS: Final = "available"
UNAVAILABLE_READINESS: Final = "unavailable"
PREFERRED_READINESS: Final = "preferred"
READINESS_MODES: Final = {
    UNKNOWN_READINESS,
    AVAILABLE_READINESS,
    UNAVAILABLE_READINESS,
    PREFERRED_READINESS,
}


@dataclass(frozen=True, slots=True)
class KnowledgeConnectionOptions:
    storage: str = ""
    knowledge_store: str = ""
    obsidian: str = UNKNOWN_READINESS


@dataclass(frozen=True, slots=True)
class DestinationClassification:
    kind: str
    vendor_hint: str
    legacy_store_type: str


def build_knowledge_connection_intent(
    text: str,
    *,
    options: KnowledgeConnectionOptions | None = None,
) -> KnowledgeConnectionIntent:
    resolved_options = options or KnowledgeConnectionOptions()
    explicit = _explicit_target(resolved_options)
    readiness_mode = _connection_readiness_mode(resolved_options, explicit)
    classification = _classify_destination(text, explicit, readiness_mode)
    return {
        "schema_version": CONNECTION_INTENT_SCHEMA_VERSION,
        "status": "prepared",
        "kind": classification.kind,
        "explicit_target": explicit,
        "vendor_hint": classification.vendor_hint,
        "legacy_store_type": classification.legacy_store_type,
        "mode": readiness_mode,
        "readiness": _readiness_label(readiness_mode),
        "requested_capability": "persist source inboxes, notes, briefs, and unresolved verification gaps",
        "capabilities": _capabilities_for(classification.kind),
        "write_observed": False,
        "query_observed": False,
        "requires_observed_write_evidence": True,
        "boundary": "A knowledge destination preference is not write evidence or proof that the store is configured.",
    }


def build_knowledge_connection_readiness(intent: KnowledgeConnectionIntent) -> KnowledgeConnectionIntent:
    missing: list[str] = []
    if not intent["explicit_target"] and intent["kind"] == "unknown_external_destination":
        missing.append("destination name or storage type")
    if intent["readiness"] == "not_checked":
        missing.append("operator confirmation that the destination exists")
    return {
        "schema_version": CONNECTION_READINESS_SCHEMA_VERSION,
        "status": "prepared",
        "kind": str(intent["kind"]),
        "vendor_hint": str(intent["vendor_hint"]),
        "readiness": str(intent["readiness"]),
        "missing_facts": missing,
        "write_observed": False,
        "query_observed": False,
        "boundary": "Readiness is prepared guidance only; it is not external write or query evidence.",
    }


def build_knowledge_store_intent(
    text: str,
    *,
    options: KnowledgeConnectionOptions | None = None,
) -> KnowledgeStoreIntent:
    connection = build_knowledge_connection_intent(text, options=options)
    return {
        "schema_version": STORE_INTENT_SCHEMA_VERSION,
        "status": "prepared",
        "type": str(connection["legacy_store_type"]),
        "explicit_target": str(connection["explicit_target"]),
        "vendor_hint": str(connection["vendor_hint"]),
        "mode": str(connection["mode"]),
        "readiness": str(connection["readiness"]),
        "requested_capability": str(connection["requested_capability"]),
        "write_observed": False,
        "requires_observed_write_evidence": True,
        "boundary": "A knowledge-store preference is not write evidence or proof that the store is configured.",
    }


def _explicit_target(options: KnowledgeConnectionOptions) -> str:
    return options.knowledge_store.strip() or options.storage.strip()


def _connection_readiness_mode(options: KnowledgeConnectionOptions, explicit_target: str) -> str:
    readiness_mode = _readiness_mode(options.obsidian)
    if explicit_target and readiness_mode == UNKNOWN_READINESS:
        return PREFERRED_READINESS
    return readiness_mode


def _classify_destination(text: str, explicit_target: str, readiness_mode: str) -> DestinationClassification:
    explicit_source = explicit_target.casefold()
    concept_source = f"{text} {explicit_target}".casefold()
    if _contains_any(explicit_source, ("obsidian", "vault", "옵시디언", "볼트")):
        return DestinationClassification("markdown_vault", "obsidian", "obsidian_vault")
    if readiness_mode in {AVAILABLE_READINESS, PREFERRED_READINESS} and not explicit_target:
        return DestinationClassification("markdown_vault", "obsidian", "obsidian_vault")
    if _contains_any(concept_source, ("notion", "노션")):
        return DestinationClassification("notion_knowledge_base", "notion", "notion_workspace")
    if _contains_any(concept_source, ("google drive", "gdrive", "google docs", "구글 드라이브")):
        return DestinationClassification("google_document_store", "google", "google_drive")
    if _contains_any(concept_source, ("database", "db", "데이터베이스")):
        return DestinationClassification("database", "", "database")
    if _contains_any(concept_source, ("markdown", "md", "folder", "폴더", "마크다운")):
        return DestinationClassification("markdown_folder", "", "markdown_folder")
    if explicit_target:
        return DestinationClassification("unknown_external_destination", "", "local_markdown_folder")
    return DestinationClassification("local_markdown_folder", "", "local_markdown_folder")


def _capabilities_for(kind: str) -> list[str]:
    if kind == "unknown_external_destination":
        return ["prepare destination questions", "preserve source-backed wiki structure"]
    return ["prepare destination-aware wiki structure", "preserve source-backed retrieval hints"]


def _contains_any(source: str, terms: tuple[str, ...]) -> bool:
    return any(term.casefold() in source for term in terms)


def _readiness_mode(mode: str) -> str:
    normalized = str(mode or UNKNOWN_READINESS).strip().lower()
    if normalized in READINESS_MODES:
        return normalized
    return UNKNOWN_READINESS


def _readiness_label(mode: str) -> str:
    normalized = _readiness_mode(mode)
    match normalized:
        case "preferred":
            return "operator_prefers_if_available"
        case "available":
            return "operator_supplied_available"
        case "unavailable":
            return "not_available"
        case "unknown":
            return "not_checked"
        case unreachable:
            assert_never(unreachable)
