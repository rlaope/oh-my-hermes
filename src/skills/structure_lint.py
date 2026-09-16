from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
from typing import Protocol
import unicodedata

from .catalog import primary_harness_for_skill
from .catalog_types import HarnessDefinition, SkillDefinition

SKILL_STRUCTURE_LINT_SCHEMA_VERSION = "omh_skill_structure_lint/v1"
STRUCTURE_LINT_RULE_IDS = (
    "SKILL_CANONICAL_IDENTITY_UNIQUE",
    "SKILL_CATALOG_CONTRACT",
    "SKILL_CATALOG_NONEMPTY",
    "SKILL_CONTEXT_BUDGET",
    "SKILL_EXECUTABLE_CONSUMER",
    "SKILL_FRONTMATTER_FIELDS",
    "SKILL_GENERATED_PARITY",
    "SKILL_HARNESS_RESOLVES",
    "SKILL_RENDERED_IDENTITY_UNIQUE",
    "SKILL_TRIGGER_FORMAT",
)
# Always-loaded body ceiling per skill. Ratchet, not a target: raise it only
# with the reason written here. 24_000 held until 2026-09-11, when the
# ultrawork body measured 25_078 bytes after the seven executing-engine bars
# gained the follow-up-authority and closing-brief rules (Codex Desktop prompt
# review, MODEL_OPTI.md); ultrawork already sat 9 bytes under the old ceiling.
# 25_100 held until 2026-09-12, when the ultrawork body measured 25_475 bytes
# after the #1494 executor-owned loop-driver and #1495 advisory
# handoff-risk-scan guidance joined the always-loaded catalog text
# (issues-1485-1505 delivery); the dispatching lane must read both before
# acting, and the sibling FULL_PROFILE_SKILL_BODY_CHAR_LIMIT pin in
# src/maintenance/release.py was re-derived from the same producer on the
# same branch. Warranted always-loaded growth, not drift.
# 25_500 held until 2026-09-16, when the ultrawork body measured 25_661 bytes
# after its todo-initialization directive moved out of the quality bar (which
# renders under `## Catalog Metadata`, past the point a run has already begun)
# into the new `## First Steps` section under `## Why This Exists`, and a
# `Completion Checklist` line was added so a run cannot read as complete while
# the plan was never declared. The directive is the same text in a different
# place; the 186 bytes are the heading and the checklist line. Warranted
# always-loaded growth, not drift.
STRUCTURE_LINT_SKILL_BODY_BYTE_CEILING = 25_700
_PICKER_SAFE_TRIGGER = re.compile(r"^[0-9A-Za-z\uac00-\ud7a3][0-9A-Za-z\uac00-\ud7a3 _.-]*$")
_FRONTMATTER = re.compile(r'^---\nname: (.+)\ndescription: (.+)\nmetadata:\n(.*?)\n---\n', re.DOTALL)
_JSON_STRING = re.compile(r'"(?:[^"\\\x00-\x1f]|\\["\\/bfnrt]|\\u[0-9A-Fa-f]{4})*"')


class CatalogContractValidator(Protocol):
    def __call__(self, definition: SkillDefinition) -> list[str]: ...


@dataclass(frozen=True, slots=True)
class StructureLintInputs:
    definitions: list[SkillDefinition]
    harnesses: list[HarnessDefinition]
    full_catalog: bool
    validate_definition: CatalogContractValidator


def build_skill_structure_lint_payload(inputs: StructureLintInputs) -> dict[str, object]:
    """Return deterministic catalog-projection structure findings."""
    resolved = list(inputs.definitions)
    violations = _aggregate_violations(resolved)
    harness_names = {harness.name for harness in inputs.harnesses}
    for definition in sorted(resolved, key=lambda item: item.name):
        violations.extend(_definition_violations(definition, harness_names, inputs.validate_definition))
    payload: dict[str, object] = {
        "schema_version": SKILL_STRUCTURE_LINT_SCHEMA_VERSION,
        "ok": not violations,
        "checks": "structure_only",
        "proves_host_loading": False,
        "catalog_scope": "full_catalog" if inputs.full_catalog else "supplied_subset",
        "skill_count": len(resolved),
        "rules": list(STRUCTURE_LINT_RULE_IDS),
        "violations": violations,
    }
    if inputs.full_catalog:
        payload["expected_skill_count"] = len(resolved)
    return payload


def _aggregate_violations(definitions: list[SkillDefinition]) -> list[dict[str, str]]:
    if not definitions:
        return [{"rule": "SKILL_CATALOG_NONEMPTY", "skill": "<catalog>", "detail": "catalog must contain at least one skill definition"}]
    found: list[dict[str, str]] = []
    canonical = Counter(item.name for item in definitions)
    duplicate_canonical = sorted(name for name, count in canonical.items() if count > 1)
    if duplicate_canonical:
        found.append({"rule": "SKILL_CANONICAL_IDENTITY_UNIQUE", "skill": "<catalog>", "detail": f"duplicate canonical skill identities: {duplicate_canonical}"})
    rendered = Counter(_rendered_identity(item) for item in definitions)
    duplicate_rendered = sorted(name for name, count in rendered.items() if name and count > 1)
    if duplicate_rendered and not duplicate_canonical:
        found.append({"rule": "SKILL_RENDERED_IDENTITY_UNIQUE", "skill": "<catalog>", "detail": f"duplicate rendered skill identities: {duplicate_rendered}"})
    return found


def _definition_violations(
    definition: SkillDefinition,
    harness_names: set[str],
    validate_definition: CatalogContractValidator,
) -> list[dict[str, str]]:
    found: list[dict[str, str]] = []
    for rule, detail in (
        ("SKILL_CATALOG_CONTRACT", _lint_catalog_contract(definition, validate_definition)),
        ("SKILL_CONTEXT_BUDGET", _lint_context_budget(definition)),
        ("SKILL_EXECUTABLE_CONSUMER", _lint_executable_consumer(definition)),
        ("SKILL_FRONTMATTER_FIELDS", _lint_frontmatter_fields(definition)),
        ("SKILL_GENERATED_PARITY", _lint_generated_parity(definition)),
        ("SKILL_HARNESS_RESOLVES", _lint_harness_resolves(definition, harness_names)),
        ("SKILL_TRIGGER_FORMAT", _lint_trigger_format(definition)),
    ):
        if detail:
            found.append({"rule": rule, "skill": definition.name, "detail": detail})
    return found


def _lint_catalog_contract(
    definition: SkillDefinition, validate_definition: CatalogContractValidator
) -> str:
    errors = validate_definition(definition)
    return "; ".join(sorted(error for error in errors if "primary_harness is unknown" not in error))


def _rendered_frontmatter(definition: SkillDefinition) -> dict[str, str] | None:
    from .render import workflow_skill_from_definition

    try:
        content = workflow_skill_from_definition(definition, definition.name).content
    except (ValueError, KeyError):
        return None
    match = _FRONTMATTER.match(content)
    if match is None:
        return None
    name = _decode_scalar(match.group(1))
    description = _decode_scalar(match.group(2))
    if name is None or description is None:
        return None
    metadata_matches: list[tuple[str, str]] = re.findall(
        r"^\s+([a-z_]+): (.+)$", match.group(3), re.MULTILINE
    )
    metadata = {key: value.strip() for key, value in metadata_matches}
    return {"name": name, "description": description, **metadata}


def _decode_scalar(encoded: str) -> str | None:
    if _JSON_STRING.fullmatch(encoded) is None:
        return None
    for escape_match in re.finditer(r"\\u([0-9A-Fa-f]{4})", encoded):
        if unicodedata.category(chr(int(escape_match.group(1), 16))) == "Cc":
            return None
    if re.search(r"\\[bfnrt]", encoded):
        return None
    decoded = encoded[1:-1].replace(r'\"', '"').replace(r"\\", "\\").replace(r"\/", "/")
    if not decoded.strip() or decoded != decoded.strip():
        return None
    return decoded


def _lint_frontmatter_fields(definition: SkillDefinition) -> str:
    from .render import frontmatter_description

    try:
        _description = frontmatter_description(definition)
    except ValueError as exc:
        return f"frontmatter description cannot be rendered: {exc}"
    rendered = _rendered_frontmatter(definition)
    if rendered is None:
        return "emitted name and description must be non-empty JSON-compatible YAML double-quoted scalars without control characters"
    return ""


def _rendered_identity(definition: SkillDefinition) -> str:
    rendered = _rendered_frontmatter(definition)
    return "" if rendered is None else rendered["name"]


def _lint_harness_resolves(definition: SkillDefinition, harness_names: set[str]) -> str:
    harness = primary_harness_for_skill(definition.name)
    return "" if harness in harness_names else f"primary harness does not resolve: {harness}"


def _lint_generated_parity(definition: SkillDefinition) -> str:
    rendered = _rendered_frontmatter(definition)
    if rendered is None:
        return ""
    mismatched = sorted(
        key
        for key, expected in (
            ("category", definition.category),
            ("phase", definition.phase),
            ("role", definition.hermes_role),
            ("quality_tier", definition.quality_tier),
        )
        if rendered.get(key) != expected
    )
    return "" if not mismatched else f"generated frontmatter does not match the catalog definition: {mismatched}"


def _lint_trigger_format(definition: SkillDefinition) -> str:
    malformed = [
        trigger
        for trigger in definition.triggers
        if not trigger.strip() or trigger != trigger.strip() or "\n" in trigger
    ]
    if malformed:
        return f"triggers must be single-line, stripped, non-empty strings: {sorted(malformed)}"
    if definition.category == "router":
        return ""
    if any(_PICKER_SAFE_TRIGGER.fullmatch(value) for value in (*definition.triggers, *definition.aliases)):
        return ""
    return "no trigger or alias survives frontmatter encoding, so the picker cannot select this skill"


def _lint_executable_consumer(definition: SkillDefinition) -> str:
    from ..routing.recommend import _SKILL_POLICIES
    from ..wrapper.contract import _WORKFLOW_OPERATIONS_CHAT_CARDS

    card = _WORKFLOW_OPERATIONS_CHAT_CARDS.get(definition.name)
    policy = _SKILL_POLICIES.get(definition.name)
    if card is None or policy is None:
        return ""
    card_action = str(card.get("next_action", ""))
    if card_action and card_action != policy.next_action:
        return f"wrapper card and routing policy disagree on next_action: {card_action} != {policy.next_action}"
    artifact_schema = str(card.get("artifact_schema", ""))
    declared = [
        item.split(maxsplit=1)[0]
        for item in definition.artifact_expectations
        if "wrapper card recording" in item
    ]
    if declared and artifact_schema not in declared:
        return f"wrapper artifact_schema does not match the declared wrapper card: {artifact_schema}"
    return ""


def _lint_context_budget(definition: SkillDefinition) -> str:
    from .render import workflow_skill_from_definition

    try:
        template = workflow_skill_from_definition(definition, definition.name)
    except (ValueError, KeyError):
        return ""
    size = len(template.content.encode("utf-8"))
    if size > STRUCTURE_LINT_SKILL_BODY_BYTE_CEILING:
        return f"always-loaded skill body is {size} bytes, over the {STRUCTURE_LINT_SKILL_BODY_BYTE_CEILING} byte ceiling"
    return ""
