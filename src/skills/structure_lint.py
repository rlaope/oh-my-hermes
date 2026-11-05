from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import re
from typing import Protocol
import unicodedata

from .catalog import primary_harness_for_skill
from .catalog_types import (
    HarnessDefinition,
    SkillDefinition,
    _CATEGORY_RECOVERY_NOTES,
    _GENERAL_RECOVERY_NOTES,
    _HANDOFF_RECOVERY_NOTES,
)

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
    "SKILL_INDEX_OPENING_DISTINCT",
    "SKILL_RECOVERY_SPECIFIC",
    "SKILL_RENDERED_IDENTITY_UNIQUE",
    "SKILL_TRIGGER_FORMAT",
)
# Migration ratchet: a skill leaves this tuple when it gains specific recovery notes.
RECOVERY_DEFAULT_ONLY_ALLOWED: tuple[str, ...] = ()

# Per-skill SKILL.md body ceiling (paid on each load, not every request). Ratchet, not a target: raise it only
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
# 25_500 held until 2026-09-16, when the ultrawork body measured 25_836 bytes.
# Its todo-initialization directive moved out of `quality_bar` -- which renders
# under `## Catalog Metadata`, past the point a run has already begun -- into
# the new `## First Steps` section under `## Why This Exists`, and its
# `Completion Checklist` gained two lines for obligations the quality bar
# already carried but the completion contract did not: that the phase todo was
# declared, and that every Hermes-native lane was routed before dispatch. All
# three are the same text in a place a run reads; the 336 bytes are one heading
# and two checklist lines. The sibling FULL_PROFILE_SKILL_BODY_CHAR_LIMIT pin in
# src/maintenance/release.py was re-derived from its own producer on the same
# branch. Warranted always-loaded growth, not drift.
# 25_900 held until 2026-09-17, when the ultrawork body measured 25_911 bytes
# through the gate's own path, `skill_structure_lint_payload()` rendering
# `builtin_definitions()`. (A bare catalog-definition render reads 25_756 and
# is not what this gate measures; an interim revert of this ratchet was made
# on that number and undone.) The body gained one clause pointing a lane
# that must outlive the session at `references/kanban-lane.md`; the create
# recipe, the readback discipline, and the role table live in that
# reference, outside this budget. The sibling ledger pins in
# src/maintenance/release.py were re-derived from their producers on the
# same branch. Warranted always-loaded growth, not drift.
#
# 26_000 -> 26_500: `ultrawork` measures 26_493 through the same gate after
# the two executing-engine rules (follow-up authority, closing brief) and
# the per-skill tail gained the turn-ending sentence: a stop at a boundary
# or at a decision the user owns ends the turn by offering the next action
# as a question, never by declaring what will not be done. The model had
# been closing runs with "I will not merge or force-push here", which left
# the person no next move; the sentence is what every skill's stop
# condition needed and belongs in the always-loaded body because the stop
# is where it is read. Warranted always-loaded growth, not drift.
#
# 26_500 -> 26_800: `ultrawork` measures 26_730 after the tail sentence grew
# to say the reply is written in the user's own words and the host's own
# voice, with OMH's record terms kept to records and tool calls, and after
# the closing brief rule gained "in the user's words". Same reason as the
# entry above: the sentence is read where the reply is written. Warranted
# always-loaded growth, not drift.
#
# 26_800 -> 27_100: `ultrawork` measures 27_012 after the same tail sentence
# named what the voice covers: the host persona's reply language, tone,
# speech level, and sentence endings, progress updates included, with the
# user's language only where the persona sets none and OMH shaping structure
# and content only. The next hundred, 27_000, is under the measured body, so
# the ceiling is the hundred above it. "The host's own voice" alone left a
# casual-register Korean persona writing its interim progress lines in
# English (miku, 2026-09-30). Same reason as the entries above. Warranted
# always-loaded growth, not drift.
#
# 27_100 -> 27_200: `ultrawork` ships 27_156 bytes (27_089 before) once its
# `## Do Not Use When` names `decision-prototype` and `loop` by the labels
# `skill_view` loads (`omh-decision-prototype`, `ulw-loop`) and its
# frontmatter lists them as `related_skills`. A sibling named by a name the
# host cannot load is a pointer the model cannot follow, and the list is what
# `skill_view` returns beside the body. Warranted always-loaded growth, not
# drift.
#
# 27_200 -> 27_300: `ultrawork` ships 27_271 bytes once its frontmatter
# carries `license` and `author`, its `## Use When` heading becomes the
# `## When to Use` Hermes' skill linter expects, and its two shared-rail
# pointers become the `skill_view(name=..., file_path=...)` call that loads
# the rail. Same reason as the entry above: the pointer is read where the
# rail is needed. Warranted always-loaded growth, not drift.
STRUCTURE_LINT_SKILL_BODY_BYTE_CEILING = 27_300
_PICKER_SAFE_TRIGGER = re.compile(r"^[0-9A-Za-z\uac00-\ud7a3][0-9A-Za-z\uac00-\ud7a3 _.-]*$")
# `license` and `author` sit between the description and `metadata`; each
# scalar is one line, so the two scalars stop at their own line end.
_FRONTMATTER = re.compile(
    r'^---\nname: ([^\n]+)\ndescription: ([^\n]+)\n(?:license: [^\n]+\n)?(?:author: [^\n]+\n)?metadata:\n(.*?)\n---\n',
    re.DOTALL,
)
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
    violations.extend(_index_opening_violations(resolved, full_catalog=inputs.full_catalog))
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


def _index_opening_violations(
    definitions: list[SkillDefinition], *, full_catalog: bool
) -> list[dict[str, str]]:
    """Two installable skills must not open their index line with the same words.

    Hermes shows a model only the first 57 description characters of each
    skill and tells it to load any skill that is even partially relevant, so
    a shared opening is a pair the model cannot separate before paying for
    both bodies. `skill_index.index_opening` defines the opening; the reviewed
    groups and their reasons live beside it. Only installable skills count,
    because a retired definition contributes no index line.

    A supplied subset can only show a group growing or appearing. Whether a
    recorded member still shares its opening is a question about the whole
    catalog, so a stale record is reported on the full catalog only.
    """
    from .catalog import installable_skill_names
    from .render import frontmatter_description
    from .skill_index import REVIEWED_SHARED_INDEX_OPENINGS, index_opening_collisions

    installable = set(installable_skill_names())
    pairs: list[tuple[str, str]] = []
    for definition in definitions:
        if definition.name not in installable:
            continue
        # The description the frontmatter emits, rendered from THIS definition:
        # `_rendered_frontmatter` re-reads the catalog entry by name, so a
        # supplied definition's own description would never be seen there.
        try:
            pairs.append((definition.name, frontmatter_description(definition)))
        except ValueError:
            continue  # SKILL_FRONTMATTER_FIELDS reports an unrenderable description.
    live = index_opening_collisions(pairs)
    found: list[dict[str, str]] = []
    for opening, skills in sorted(live.items()):
        reviewed = REVIEWED_SHARED_INDEX_OPENINGS.get(opening)
        if reviewed is None or not skills <= reviewed[0]:
            found.append({
                "rule": "SKILL_INDEX_OPENING_DISTINCT",
                "skill": "<catalog>",
                "detail": (
                    f"skills {sorted(skills)} open their index description with the same words "
                    f"{opening!r}; make the first words name each skill's own trigger, or record the "
                    "group with a reason in REVIEWED_SHARED_INDEX_OPENINGS (src/skills/skill_index.py)"
                ),
            })
    if full_catalog:
        for opening, (skills, _reason) in sorted(REVIEWED_SHARED_INDEX_OPENINGS.items()):
            shared_now = live.get(opening, frozenset())
            if not skills <= shared_now:
                found.append({
                    "rule": "SKILL_INDEX_OPENING_DISTINCT",
                    "skill": "<catalog>",
                    "detail": (
                        f"reviewed shared opening {opening!r} records {sorted(skills)} but the catalog "
                        f"shares it among {sorted(shared_now)}; update or delete the record"
                    ),
                })
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
        ("SKILL_RECOVERY_SPECIFIC", _lint_recovery_specific(definition)),
        ("SKILL_TRIGGER_FORMAT", _lint_trigger_format(definition)),
    ):
        if detail:
            found.append({"rule": rule, "skill": definition.name, "detail": detail})
    return found


def _lint_recovery_specific(definition: SkillDefinition) -> str:
    from .catalog import installable_skill_names

    if definition.name not in installable_skill_names():
        return ""
    defaults = set(_GENERAL_RECOVERY_NOTES) | set(_HANDOFF_RECOVERY_NOTES)
    defaults.update(line for notes in _CATEGORY_RECOVERY_NOTES.values() for line in notes)
    default_only = all(line in defaults for line in definition.recovery_notes)
    if definition.name in RECOVERY_DEFAULT_ONLY_ALLOWED:
        if not default_only:
            return "skill has specific recovery notes; remove it from RECOVERY_DEFAULT_ONLY_ALLOWED"
    elif default_only:
        return "installable skill needs skill-specific recovery notes, not only library defaults"
    return ""


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
        return f"SKILL.md body (per load) is {size} bytes, over the {STRUCTURE_LINT_SKILL_BODY_BYTE_CEILING} byte ceiling"
    return ""
