"""Generated public projection of the shipped model recommendation chains.

`docs/INSTALLATION.md` publishes the shipped chains as a reader-facing table.
Before this module the table was hand-maintained: it agreed with
`SHIPPED_MODEL_RECOMMENDATIONS` only for as long as whoever retired a model
generation remembered to edit the doc too, and nothing failed when they did
not. Every other public projection of catalog data in this repository is byte-
or equality-gated, so this one was the exception.

The producer renders the whole marked region (markers included) from the
catalog, and `omh docs chain-table --check` compares bytes, which takes the
table out of human hands the same way the ULW regions are.

Two things the table shows do not exist as catalog data, so they live here and
only here:

- The display label for a model alias (`claude-fable-5-1` -> `Claude Fable
  5.1`). The alias is what routing uses; the label is what a reader needs.
- The "What it is for" phrase per surface. This is editorial one-line prose,
  and the same strings are already duplicated into `site/i18n.js` under the
  `chain.*` keys; source is the better home for them.

Both are required, not defaulted: a chain surface with no phrase, or a model
with no label, raises with the key to add and the command to rerun. A new
mixture category therefore cannot reach the shipped chains while staying
invisible in the public table — which is the point of the gate.

Effort is rendered from the catalog, never assumed, and always on the entry
that declares it. The hand-written table used a trailing token for a row whose
entries all shared an effort, which reads shorter but cannot be read back: in
`Claude Opus 5.5, GPT-6.1 Sol (medium)` the token could belong to the row or to
Sol alone, and for `last_resort.any` it then belonged to Sol alone. One rule --
`Label (effort)` per entry, nothing at all for an entry that declares none --
is longer on the uniform rows and unambiguous on every row, which is what lets
`tests/test_model_chain_table.py` read the table back into aliases and efforts
and compare it against the catalog.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Mapping, Sequence

from ..coding.model_recommendations import (
    HERMES_MODEL_SETUP_ROLE_SLOTS,
    MODEL_RECOMMENDATION_DOMAINS,
    MODEL_RECOMMENDATION_LAST_RESORT_SLOTS,
    SHIPPED_MODEL_RECOMMENDATIONS,
)
from ..coding.model_routing import MODEL_CATEGORIES

MODEL_CHAIN_TABLE_REGION_BEGIN: Final[str] = (
    "<!-- omh:model-chain-table:begin "
    "(generated: uv run python -m omh.cli docs chain-table; "
    "source: src/coding/model_recommendations.py) -->"
)
MODEL_CHAIN_TABLE_REGION_END: Final[str] = "<!-- omh:model-chain-table:end -->"

MODEL_CHAIN_TABLE_PATH: Final[str] = "docs/INSTALLATION.md"
_SOURCE_MODULE: Final[str] = "src/catalogs/model_chain_table.py"
_REGEN_COMMAND: Final[str] = "uv run python -m omh.cli docs chain-table"

# Reader-facing label per model alias. Every label a shipped chain uses names
# its generation. `deepseek-flash` is the vendor's served pointer id, which
# carries none, so its label spells the generation behind it in the vendor's
# own order, "DeepSeek V4.1 Flash" (owner decision, 2026-10-13); the alias
# stays the pointer because the endpoint rejects `deepseek-v4.1-flash`.
MODEL_DISPLAY_LABELS: Final[dict[str, str]] = {
    "claude-fable-5-1": "Claude Fable 5.1",
    "claude-haiku-4-5": "Claude Haiku 4.5",
    "claude-haiku-5-5": "Claude Haiku 5.5",
    "claude-opus-5": "Claude Opus 5",
    "claude-opus-5-5": "Claude Opus 5.5",
    "claude-sonnet-5-5": "Claude Sonnet 5.5",
    "deepseek-flash": "DeepSeek V4.1 Flash",
    "gemini-3.1-pro": "Gemini 3.1 Pro",
    "gemini-4-argon": "Gemini 4 Argon",
    "glm-5.3": "GLM 5.3",
    "glm-5.3-flash": "GLM 5.3 Flash",
    "gpt-5.6-luna": "GPT-5.6 Luna",
    "gpt-5.6-sol": "GPT-5.6 Sol",
    "gpt-5.6-terra": "GPT-5.6 Terra",
    "gpt-6-astra": "GPT-6 Astra",
    "gpt-6-luna": "GPT-6 Luna",
    "gpt-6-sol": "GPT-6 Sol",
    "gpt-6.1-sol": "GPT-6.1 Sol",
    "gpt-6.1-terra": "GPT-6.1 Terra",
    "gpt-6-cyber": "GPT-6 Cyber",
    "gpt-5.6-cyber": "GPT-5.6 Cyber",
    "gpt-6-rosalind": "GPT-6 Rosalind",
    "grok-4.7": "Grok 4.7",
    "grok-build-0.1": "Grok Build 0.1",
    "grok-code-fast": "Grok Code Fast",
    "kimi-k3": "Kimi K3",
    "kimi-k3.1-pro": "Kimi K3.1 Pro",
    "kimi-k3.1-pro-highspeed": "Kimi K3.1 Pro Highspeed",
    "qwen3-coder": "Qwen3-Coder",
}

# One editorial phrase per chain surface, keyed by the row id built below.
# Categories are keyed by their bare category name so a new category needs one
# obvious line here. Every phrase is the one its surface already published --
# in the hand-written table this region replaces, and in `site/i18n.js` under
# the matching `chain.*` key, which also carries the ko/ja/zh translations.
# Adding a category means moving its existing phrase here, not writing a new
# one; keep the register of the neighbours.
CHAIN_SURFACE_PURPOSES: Final[dict[str, str]] = {
    "role.main": "The session's own model",
    "ultrabrain": "Deepest reasoning",
    "deep": "Strong default tier",
    "architect": "Architecture and system design",
    "unspecified-high": "Default working model",
    "unspecified-low": "Cheaper fallback",
    "quick": "Short tasks",
    "writing": "Prose and docs",
    "visual-engineering": "Frontend and visual",
    "artistry": "Unconventional work",
    "capable": "Strong general work",
    "simple-work": "Small everyday tasks",
    "deep-work": "Long tasks at frontier depth",
    "google-search": "Research grounded in Google Search",
    "x-search": "Live search on X",
    "review": "A different model tries to break the diff",
    "swarm": "Many parallel workers on separate slices",
    "forensics": "Root-causing a live symptom or a captured trace",
    "synthesize": "Merging many results into one answer",
    "domain.x_platform_data": "X-platform data affinity",
    "last_resort.any": "Last resort when a chain is exhausted",
}

_EMPTY_CHAIN_CELL: Final[str] = "(none shipped)"
_TABLE_HEADER: Final[tuple[str, str]] = (
    "| Surface | What it is for | Shipped editable order |",
    "| --- | --- | --- |",
)


@dataclass(frozen=True)
class ChainTableRow:
    """One rendered row: its id, the two label cells, and the order cell."""

    row_id: str
    surface: str
    purpose: str
    order: str


def _purpose(row_id: str) -> str:
    try:
        return CHAIN_SURFACE_PURPOSES[row_id]
    except KeyError:
        raise ValueError(
            f"chain surface {row_id!r} has no 'What it is for' phrase: add "
            f"CHAIN_SURFACE_PURPOSES[{row_id!r}] in {_SOURCE_MODULE}, then run {_REGEN_COMMAND}"
        ) from None


def _label(model_alias: str) -> str:
    try:
        return MODEL_DISPLAY_LABELS[model_alias]
    except KeyError:
        raise ValueError(
            f"model alias {model_alias!r} has no display label: add "
            f"MODEL_DISPLAY_LABELS[{model_alias!r}] in {_SOURCE_MODULE}, then run {_REGEN_COMMAND}"
        ) from None


def _entries(section: object, key: str) -> tuple[dict[str, str], ...]:
    """Return (alias, effort) pairs for one catalog slot, or () when absent."""
    if not isinstance(section, Mapping):
        return ()
    chain = section.get(key)
    if not isinstance(chain, Sequence) or isinstance(chain, (str, bytes)):
        return ()
    entries: list[dict[str, str]] = []
    for candidate in chain:
        if not isinstance(candidate, Mapping):
            continue
        entries.append(
            {
                "model_alias": str(candidate.get("model_alias", "")),
                "reasoning_effort": str(candidate.get("reasoning_effort", "")),
            }
        )
    return tuple(entries)


def _render_order(entries: Sequence[Mapping[str, str]]) -> str:
    """Render one chain as reader-facing labels plus per-entry declared effort.

    Every declared effort is annotated on its own entry, and an entry that
    declares none carries no token: the catalog's empty string means the lane
    inherits, and printing a guess there would turn a missing value into a
    claim. See the module docstring for why there is no shorter row-wide form.
    """
    if not entries:
        return _EMPTY_CHAIN_CELL
    parts: list[str] = []
    for entry in entries:
        label = _label(entry["model_alias"])
        effort = entry["reasoning_effort"]
        parts.append(f"{label} (`{effort}`)" if effort else label)
    return ", ".join(parts)


def chain_table_rows(
    catalog: Mapping[str, object] = SHIPPED_MODEL_RECOMMENDATIONS,
) -> tuple[ChainTableRow, ...]:
    """Project every shipped chain surface, in catalog vocabulary order.

    The enumeration walks the four closed vocabularies rather than the
    catalog's own keys, so a surface that gains a chain cannot stay out of the
    public table and a surface that loses one still renders as `(none
    shipped)` instead of disappearing without a trace.
    """
    rows: list[ChainTableRow] = []
    for slot in HERMES_MODEL_SETUP_ROLE_SLOTS:
        row_id = f"role.{slot}"
        rows.append(
            ChainTableRow(
                row_id,
                f"Hermes `{slot}` suggestion",
                _purpose(row_id),
                _render_order(_entries(catalog.get("role_suggestions"), slot)),
            )
        )
    for category in MODEL_CATEGORIES:
        rows.append(
            ChainTableRow(
                category,
                f"`{category}`",
                _purpose(category),
                _render_order(_entries(catalog.get("categories"), category)),
            )
        )
    for domain in MODEL_RECOMMENDATION_DOMAINS:
        row_id = f"domain.{domain}"
        rows.append(
            ChainTableRow(
                row_id,
                f"`{domain}` affinity",
                _purpose(row_id),
                _render_order(_entries(catalog.get("domain_affinities"), domain)),
            )
        )
    for slot in MODEL_RECOMMENDATION_LAST_RESORT_SLOTS:
        row_id = f"last_resort.{slot}"
        rows.append(
            ChainTableRow(
                row_id,
                f"Shared final order (`last_resort.{slot}`)",
                _purpose(row_id),
                _render_order(_entries(catalog.get("last_resort"), slot)),
            )
        )
    return tuple(rows)


def model_chain_table_region() -> str:
    """The generated chain table, markers included, no trailing newline."""
    lines = [MODEL_CHAIN_TABLE_REGION_BEGIN, *_TABLE_HEADER]
    for row in chain_table_rows():
        lines.append(f"| {row.surface} | {row.purpose} | {row.order} |")
    lines.append(MODEL_CHAIN_TABLE_REGION_END)
    return "\n".join(lines)


def _region_bounds(text: str) -> tuple[int, int]:
    begin, end = MODEL_CHAIN_TABLE_REGION_BEGIN, MODEL_CHAIN_TABLE_REGION_END
    if text.count(begin) != 1 or text.count(end) != 1:
        raise ValueError(
            f"{MODEL_CHAIN_TABLE_PATH} must contain the markers {begin!r} and {end!r} "
            "exactly once each; restore them from git or re-add the region by hand once"
        )
    start = text.index(begin)
    stop = text.index(end) + len(end)
    if stop < start:
        raise ValueError(
            f"{MODEL_CHAIN_TABLE_PATH} has its chain-table end marker before the begin marker"
        )
    return start, stop


def installation_with_generated_region(text: str) -> str:
    """Return `text` with its chain-table region replaced by the generated one."""
    start, stop = _region_bounds(text)
    return text[:start] + model_chain_table_region() + text[stop:]


def _parsed_rows(region: str) -> dict[str, tuple[str, str]]:
    """Map the surface cell to (purpose, order) for every table row present."""
    parsed: dict[str, tuple[str, str]] = {}
    for line in region.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|") or not stripped.endswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) != 3:
            continue
        if cells[0] in {"Surface", "---"}:
            continue
        parsed[cells[0]] = (cells[1], cells[2])
    return parsed


def model_chain_table_drift(text: str) -> tuple[str, ...]:
    """Name every disagreement between the documented table and the chains.

    A byte comparison alone reports that the region is stale, which is the
    symptom; these findings are the cause, one line per row, so the reader
    knows which chain moved without diffing the file by hand.
    """
    start, stop = _region_bounds(text)
    current = text[start:stop]
    if current == model_chain_table_region():
        return ()
    documented = _parsed_rows(current)
    expected = {row.surface: (row.purpose, row.order) for row in chain_table_rows()}
    findings: list[str] = []
    for surface, (purpose, order) in expected.items():
        if surface not in documented:
            findings.append(
                f"row {surface} is a shipped chain surface but is missing from the table "
                f"(expected: {purpose} | {order})"
            )
            continue
        documented_purpose, documented_order = documented[surface]
        if documented_order != order:
            findings.append(
                f"row {surface} documents the order {documented_order!r} "
                f"but the shipped chain renders {order!r}"
            )
        if documented_purpose != purpose:
            findings.append(
                f"row {surface} documents the purpose {documented_purpose!r} "
                f"but the catalog declares {purpose!r}"
            )
    for surface in documented:
        if surface not in expected:
            findings.append(
                f"row {surface} is documented but is not a shipped chain surface"
            )
    documented_order_of_rows = [key for key in documented if key in expected]
    expected_order_of_rows = [key for key in expected if key in documented]
    if documented_order_of_rows != expected_order_of_rows:
        findings.append(
            "table rows are in a different order than the catalog: documented "
            f"{documented_order_of_rows}, catalog {expected_order_of_rows}"
        )
    if not findings:
        findings.append(
            "the region text differs from the generated table outside the row cells "
            "(header, separator, spacing, or marker line)"
        )
    return tuple(findings)
