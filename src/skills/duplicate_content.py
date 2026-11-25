"""Cross-surface duplicate-content detection and suppression (backlog item E).

`src/skills/context_cost.py` (#634) already measures duplicate bytes *within
one surface kind*: byte-identical `##` sections repeated across different
`SKILL.md` bodies. `tests/test_skill_density_gate.py` (#1201) measures
repetition *inside a single skill's own body*. Neither answers the question
this module answers: when Hermes loads more than one OMH surface into the
same turn -- the always-on awareness primer, the workspace router-profile
snippet, the selected skill's body, and that skill's on-demand reference
files -- does the same paragraph get paid for twice *across* those surface
kinds?

In this codebase, "workflow context cards" (`awareness_workflow_context_markdown`
in `plugin_bundle/omh/awareness.py`) are rendered directly into each skill
body rather than delivered as an independently-loaded surface, so they are
covered here under the ``skill_body`` kind rather than a fifth kind.

Detection and suppression are both normalized-paragraph operations:

- A "block" is a blank-line-delimited paragraph of at least
  ``MIN_BLOCK_CHARS`` characters (below that, matches are common short
  phrases rather than owned content).
- Two blocks are the same content if their whitespace-collapsed text is
  byte-identical.
- Surfaces are deduped in the caller-supplied order (first occurrence wins
  and becomes the block's "owner"); a later surface of a *different* kind
  that repeats the block is a cross-surface duplicate.
- A cross-surface duplicate is either suppressed (its text is replaced by a
  short deterministic pointer line naming the owning surface) or, if its
  normalized text matches ``ALLOWLISTED_DUPLICATE_BLOCKS``, left untouched
  because the duplication is intentional and justified there.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .catalog_types import DELEGATION_TRANSPARENCY_RULES
from .packaging import builtin_skill_reference_templates, builtin_skill_templates

_BLOCK_SPLIT_RE = re.compile(r"\n\s*\n")
_WHITESPACE_RE = re.compile(r"\s+")

MIN_BLOCK_CHARS = 40
POINTER_LINE_PREFIX = "> [duplicate content suppressed; see"


@dataclass(frozen=True)
class Surface:
    """One independently-loaded (or independently-generated) OMH surface."""

    surface_id: str
    kind: str
    content: str


@dataclass(frozen=True)
class CrossSurfaceDuplicate:
    normalized: str
    owner_surface: str
    duplicate_surface: str
    byte_len: int
    allowlist_reason: str | None

    @property
    def allowlisted(self) -> bool:
        return self.allowlist_reason is not None


def normalize_block(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text).strip()


def _paragraph_spans(content: str) -> list[tuple[int, int, str]]:
    """Return `(start, end, text)` for each block, positions exact in `content`."""
    spans: list[tuple[int, int, str]] = []
    cursor = 0
    boundaries = [m.span() for m in _BLOCK_SPLIT_RE.finditer(content)]
    boundaries.append((len(content), len(content)))
    for boundary_start, boundary_end in boundaries:
        raw = content[cursor:boundary_start]
        block = raw.strip()
        if len(block) >= MIN_BLOCK_CHARS:
            offset = raw.index(block)
            start = cursor + offset
            spans.append((start, start + len(block), block))
        cursor = boundary_end
    return spans


def paragraph_blocks(content: str) -> list[str]:
    return [text for _, _, text in _paragraph_spans(content)]


def _delegation_transparency_allowlisted_block() -> str:
    return normalize_block("\n".join(f"- {rule}" for rule in DELEGATION_TRANSPARENCY_RULES))


# Blocks that intentionally repeat across surface kinds. Keyed by the block's
# normalized text; each entry must carry a reason a reviewer can check against
# the actual duplication, not just a label.
ALLOWLISTED_DUPLICATE_BLOCKS: dict[str, str] = {
    _delegation_transparency_allowlisted_block(): (
        "Delegation transparency rules (commit ad62b9a1) are rendered into both every "
        "handoff-guide/handoff-gated skill body and the shared skill-common-rail reference "
        "on purpose: a handoff-gated skill must state its own transparency obligations "
        "without depending on the agent choosing to fetch the on-demand reference first."
    ),
    normalize_block(
        "- The request is already handled by a narrower explicit skill with stronger evidence.\n"
        "- The user asks OMH to secretly run external platforms, connectors, schedulers, file exports, or runtime agents.\n"
        "- The only safe answer is to ask for missing authority, credentials, target, or observed evidence first."
    ): (
        "Default feature-surface Do-Not-Use boundary bullets appear in bespoke feature-surface "
        "skill bodies (such as `memory-new`) and in progressive-disclosure `references/full-contract.md` "
        "files for feature-surface workflow skills; each skill's full contract stays self-contained."
    ),
    normalize_block(
        "- user request\n- target context\n- delivery or status expectation\n- known missing evidence"
    ): (
        "Default feature-surface required-input bullets appear in bespoke feature-surface skill "
        "bodies (such as `memory-new`) and in progressive-disclosure `references/full-contract.md` "
        "files so each skill's on-demand contract remains self-contained."
    ),
}


def detect_cross_surface_duplicates(surfaces: list[Surface]) -> list[CrossSurfaceDuplicate]:
    """Find blocks repeated verbatim across surfaces of different kinds.

    `surfaces` order is the precedence order: the first surface to emit a
    given normalized block owns it. Same-kind repeats (e.g. two skill bodies
    sharing a heading) are out of scope here -- that is `context_cost.py`'s
    per-heading measurement -- so only a later surface of a *different* kind
    is reported.
    """
    owners: dict[str, tuple[str, str]] = {}  # normalized -> (surface_id, kind)
    duplicates: list[CrossSurfaceDuplicate] = []
    for surface in surfaces:
        for block in paragraph_blocks(surface.content):
            normalized = normalize_block(block)
            owner = owners.get(normalized)
            if owner is None:
                owners[normalized] = (surface.surface_id, surface.kind)
                continue
            owner_id, owner_kind = owner
            if owner_kind == surface.kind:
                continue
            duplicates.append(
                CrossSurfaceDuplicate(
                    normalized=normalized,
                    owner_surface=owner_id,
                    duplicate_surface=surface.surface_id,
                    byte_len=len(block),
                    allowlist_reason=ALLOWLISTED_DUPLICATE_BLOCKS.get(normalized),
                )
            )
    return duplicates


def _pointer_line(owner_surface: str) -> str:
    return f"{POINTER_LINE_PREFIX} `{owner_surface}`.]"


def suppress_duplicates(
    surfaces: list[Surface], duplicates: list[CrossSurfaceDuplicate]
) -> list[Surface]:
    """Replace every non-allowlisted duplicate block with a deterministic pointer line.

    Deterministic: same `surfaces` + `duplicates` input always produces the
    same output, independent of dict/set iteration order, because
    replacement order is driven by span position within each surface.
    """
    owner_by_duplicate_surface: dict[str, dict[str, str]] = {}
    for duplicate in duplicates:
        if duplicate.allowlisted:
            continue
        owner_by_duplicate_surface.setdefault(duplicate.duplicate_surface, {})[
            duplicate.normalized
        ] = duplicate.owner_surface

    suppressed: list[Surface] = []
    for surface in surfaces:
        replacements = owner_by_duplicate_surface.get(surface.surface_id)
        if not replacements:
            suppressed.append(surface)
            continue
        spans = _paragraph_spans(surface.content)
        new_content = surface.content
        for start, end, block in sorted(spans, key=lambda span: span[0], reverse=True):
            owner_surface = replacements.get(normalize_block(block))
            if owner_surface is None:
                continue
            new_content = new_content[:start] + _pointer_line(owner_surface) + new_content[end:]
        suppressed.append(Surface(surface.surface_id, surface.kind, new_content))
    return suppressed


def assembled_surfaces_for_measurement() -> list[Surface]:
    """The deterministic, ordered surface set for the real OMH corpus.

    Order matters: it is the precedence order for ownership. The always-on
    surfaces come first because they load before a skill is ever selected;
    skill bodies then references, both sorted by name for determinism.
    """
    from ..omh.snippet import WORKSPACE_SNIPPET
    from ..plugin_bundle.omh.awareness import awareness_primer_context, awareness_primer_markdown

    surfaces = [
        Surface("awareness:primer_context", "awareness_primer", awareness_primer_context()),
        Surface("awareness:primer_markdown", "awareness_primer", awareness_primer_markdown()),
        Surface("router:workspace_snippet", "router_profile", WORKSPACE_SNIPPET),
    ]
    templates = sorted(builtin_skill_templates(), key=lambda template: template.name)
    for template in templates:
        surfaces.append(Surface(f"skill_body:{template.name}", "skill_body", template.content))
    references = sorted(
        builtin_skill_reference_templates(),
        key=lambda template: (template.skill_name, template.relative_path),
    )
    for reference in references:
        surface_id = f"reference:{reference.skill_name}/{reference.relative_path}"
        surfaces.append(Surface(surface_id, "reference", reference.content))
    return surfaces


def cross_surface_duplicate_profile() -> dict[str, object]:
    """Measured before/after report for the real assembled corpus."""
    surfaces = assembled_surfaces_for_measurement()
    duplicates = detect_cross_surface_duplicates(surfaces)
    suppressed_surfaces = suppress_duplicates(surfaces, duplicates)

    bytes_before = sum(len(surface.content) for surface in surfaces)
    bytes_after = sum(len(surface.content) for surface in suppressed_surfaces)
    allowlisted = [duplicate for duplicate in duplicates if duplicate.allowlisted]
    suppressible = [duplicate for duplicate in duplicates if not duplicate.allowlisted]

    return {
        "surface_count": len(surfaces),
        "surface_kinds": sorted({surface.kind for surface in surfaces}),
        "bytes_before": bytes_before,
        "bytes_after": bytes_after,
        "bytes_saved": bytes_before - bytes_after,
        "duplicate_count": len(duplicates),
        "allowlisted_bytes": sum(duplicate.byte_len for duplicate in allowlisted),
        "suppressible_bytes": sum(duplicate.byte_len for duplicate in suppressible),
        "duplicates": [
            {
                "owner_surface": duplicate.owner_surface,
                "duplicate_surface": duplicate.duplicate_surface,
                "byte_len": duplicate.byte_len,
                "allowlisted": duplicate.allowlisted,
                "allowlist_reason": duplicate.allowlist_reason,
            }
            for duplicate in duplicates
        ],
    }
