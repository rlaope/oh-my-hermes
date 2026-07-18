from __future__ import annotations

from copy import deepcopy
import re
from typing import Any, Final


DESIGN_ORCHESTRATION_SCHEMA_VERSION: Final = "design_orchestration/v1"
DESIGN_SURFACES: Final = (
    "landing_page",
    "application_shell",
    "workflow_screen",
    "component_set",
    "document",
    "mixed",
)
DESIGN_AUDIENCES: Final = ("customer", "operator", "developer", "mixed")
DESIGN_PRIMARY_TASKS: Final = ("discover", "decide", "create", "manage", "recover", "mixed")
DESIGN_PLATFORMS: Final = ("web", "mobile", "desktop", "document", "mixed")
DESIGN_MODES: Final = ("new", "redesign", "quality_recovery")
DESIGN_REFERENCE_PROVENANCES: Final = ("project_local", "user_supplied", "hermes_reference")
DESIGN_REFERENCE_KINDS: Final = (
    "design_system",
    "component_inventory",
    "brand_reference",
    "route_inventory",
    "visual_reference",
)
DESIGN_HIERARCHIES: Final = ("task_first", "evidence_first", "content_first")
DESIGN_PALETTES: Final = ("restrained_neutral", "contextual_accent", "high_contrast")
DESIGN_TYPOGRAPHIES: Final = ("editorial_serif", "system_sans", "utilitarian_mono")
DESIGN_LAYOUTS: Final = ("single_column", "split_panel", "editorial_grid")
DESIGN_SIGNATURE_ELEMENTS: Final = ("evidence_rail", "decision_map", "progress_trace", "none")
DESIGN_AVOID_PATTERNS: Final = (
    "generic_glass",
    "decorative_gradient",
    "card_wall",
    "placeholder_copy",
    "tiny_text",
    "weak_hierarchy",
)
DESIGN_LANE_COMPOSITION: Final = (
    "design-quality-gate",
    "frontend",
    "accessibility-audit",
    "visual-qa",
)
_REFERENCE_ID_PATTERN: Final = re.compile(r"^design_ref_[A-Fa-f0-9]{16,64}$")


def _require_choice(value: str, choices: tuple[str, ...], label: str) -> str:
    if value not in choices:
        raise ValueError(f"{label} is invalid")
    return value


def _build_context_reference(descriptor: tuple[str, str, str]) -> dict[str, object]:
    reference_kind, reference_id, provenance = descriptor
    _require_choice(reference_kind, DESIGN_REFERENCE_KINDS, "context reference kind")
    if not _REFERENCE_ID_PATTERN.fullmatch(reference_id):
        raise ValueError("context reference_id is invalid")
    _require_choice(provenance, DESIGN_REFERENCE_PROVENANCES, "context reference provenance")
    return {
        "reference_id": reference_id,
        "provenance": provenance,
        "reference_kind": reference_kind,
        "content_retained": False,
    }


def build_design_orchestration(
    *,
    surface: str,
    audience: str,
    primary_task: str,
    platform: str,
    mode: str,
    context_references: tuple[tuple[str, str, str], ...],
    hierarchy: str,
    palette: str,
    typography: str,
    layout: str,
    signature_element: str,
    avoid_patterns: tuple[str, ...],
) -> dict[str, object]:
    _require_choice(surface, DESIGN_SURFACES, "surface")
    _require_choice(audience, DESIGN_AUDIENCES, "audience")
    _require_choice(primary_task, DESIGN_PRIMARY_TASKS, "primary_task")
    _require_choice(platform, DESIGN_PLATFORMS, "platform")
    _require_choice(mode, DESIGN_MODES, "mode")
    if not 1 <= len(context_references) <= 5:
        raise ValueError("context_references must contain between one and five descriptors")
    references = [_build_context_reference(descriptor) for descriptor in context_references]
    reference_ids = [str(reference["reference_id"]) for reference in references]
    if len(set(reference_ids)) != len(reference_ids):
        raise ValueError("context reference_id values must be unique")
    _require_choice(hierarchy, DESIGN_HIERARCHIES, "hierarchy")
    _require_choice(palette, DESIGN_PALETTES, "palette")
    _require_choice(typography, DESIGN_TYPOGRAPHIES, "typography")
    _require_choice(layout, DESIGN_LAYOUTS, "layout")
    _require_choice(signature_element, DESIGN_SIGNATURE_ELEMENTS, "signature_element")
    if not 1 <= len(avoid_patterns) <= len(DESIGN_AVOID_PATTERNS):
        raise ValueError("avoid_patterns must contain between one and six values")
    for pattern in avoid_patterns:
        _require_choice(pattern, DESIGN_AVOID_PATTERNS, "avoid_pattern")
    if len(set(avoid_patterns)) != len(avoid_patterns):
        raise ValueError("avoid_patterns must be unique")
    return {
        "schema_version": DESIGN_ORCHESTRATION_SCHEMA_VERSION,
        "status": "prepared_not_observed",
        "intent": {
            "surface": surface,
            "audience": audience,
            "primary_task": primary_task,
            "platform": platform,
            "mode": mode,
        },
        "context_references": references,
        "direction": {
            "hierarchy": hierarchy,
            "palette": palette,
            "typography": typography,
            "layout": layout,
            "signature_element": signature_element,
            "avoid_patterns": list(avoid_patterns),
        },
        "lane_composition": list(DESIGN_LANE_COMPOSITION),
        "executor_handoff": {
            "owner": "executor_neutral",
            "status": "executor_selection_required",
            "dispatch_observed": False,
        },
        "required_visual_evidence": {
            "viewport_classes": ["mobile", "desktop"],
            "required_states": ["default", "empty", "error", "focus"],
            "capture_freshness": "after_last_ui_change",
            "visual_verdict": "not_observed",
        },
        "stop_conditions": [
            "No opaque project, user, or Hermes context reference is available.",
            "The requested direction needs source content, brand facts, or visual evidence not represented by this prepared card.",
            "Raw source, prompts, assets, URLs, file paths, or private content would be needed in this metadata-only contract.",
        ],
        "claim_boundary": (
            "This prepared design orchestration records only bounded design intent, opaque context references, direction vocabulary, "
            "downstream lane composition, and evidence requirements. It does not select or dispatch an executor, change code, render a "
            "surface, perform accessibility or visual QA, review, run CI, deploy, or merge."
        ),
    }


def _context_descriptors(value: object) -> tuple[tuple[str, str, str], ...] | None:
    if not isinstance(value, list):
        return None
    descriptors: list[tuple[str, str, str]] = []
    for reference in value:
        if not isinstance(reference, dict) or set(reference) != {
            "reference_id", "provenance", "reference_kind", "content_retained"
        }:
            return None
        reference_id = reference.get("reference_id")
        provenance = reference.get("provenance")
        reference_kind = reference.get("reference_kind")
        if not all(isinstance(item, str) for item in (reference_id, provenance, reference_kind)):
            return None
        if reference.get("content_retained") is not False:
            return None
        descriptors.append((reference_kind, reference_id, provenance))
    return tuple(descriptors)


def validate_design_orchestration(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["design orchestration must be an object"]
    required = {
        "schema_version",
        "status",
        "intent",
        "context_references",
        "direction",
        "lane_composition",
        "executor_handoff",
        "required_visual_evidence",
        "stop_conditions",
        "claim_boundary",
    }
    if set(value) != required:
        return ["design orchestration keys are invalid"]
    intent = value.get("intent")
    direction = value.get("direction")
    descriptors = _context_descriptors(value.get("context_references"))
    if not isinstance(intent, dict) or set(intent) != {"surface", "audience", "primary_task", "platform", "mode"}:
        return ["design orchestration intent is invalid"]
    if not isinstance(direction, dict) or set(direction) != {
        "hierarchy", "palette", "typography", "layout", "signature_element", "avoid_patterns"
    }:
        return ["design orchestration direction is invalid"]
    if descriptors is None or not all(isinstance(item, str) for item in intent.values()):
        return ["design orchestration context references are invalid"]
    avoid_patterns = direction.get("avoid_patterns")
    if not isinstance(avoid_patterns, list) or not all(isinstance(item, str) for item in avoid_patterns):
        return ["design orchestration avoid_patterns are invalid"]
    try:
        expected = build_design_orchestration(
            surface=intent["surface"],
            audience=intent["audience"],
            primary_task=intent["primary_task"],
            platform=intent["platform"],
            mode=intent["mode"],
            context_references=descriptors,
            hierarchy=direction.get("hierarchy"),
            palette=direction.get("palette"),
            typography=direction.get("typography"),
            layout=direction.get("layout"),
            signature_element=direction.get("signature_element"),
            avoid_patterns=tuple(avoid_patterns),
        )
    except ValueError as exc:
        return [str(exc)]
    return [] if value == expected else ["design orchestration values are invalid"]


def compact_design_orchestration(value: Any) -> dict[str, object]:
    if not isinstance(value, dict) or validate_design_orchestration(value):
        return {}
    return deepcopy(value)
