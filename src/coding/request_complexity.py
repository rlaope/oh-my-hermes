"""Deterministic request-complexity scoring (`request_complexity/v1`).

`score_request_complexity` is a pure function over the request text and the
routed skill name: same inputs, byte-identical payload, no I/O, no clock, no
environment reads, no network, no model. It reports how much work a request
looks like, so a prepared handoff can RECOMMEND a model class and reasoning
effort with every input disclosed.

Three boundaries hold this module honest:

- **Advisory only.** The tier never becomes a route. `model_routing` keeps its
  documented contract that role/depth/scale are DECLARED by the caller and
  never inferred from phrasing; this scorer produces a separate recommendation
  block that a human or a caller may then declare. Nothing here is imported by
  `resolve_model_route`, and a test pins that direction.
- **Explainable from the payload alone.** Every point in `score` comes from a
  named signal in `signals`, each carrying its weight and the evidence that
  fired it. `score == sum(signal["weight"] for signal in signals)` is an
  invariant, not a coincidence, so a tier can always be traced back to words.
- **The user outranks the score.** An explicit `--model`/`--effort` (or a
  configured equivalent) supersedes the recommendation, and the payload says
  so in `status` rather than quietly dropping the suggestion.

Model names are never written here. A tier maps to a model *class* — a member
of `MODEL_CATEGORIES` — which resolves against the user's own configured
chains (`<omh-home>/routing/model-chains.json` merged over the shipped
defaults). A user who rewrote a chain gets their own models back.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Final, Mapping, Sequence

from ..routing.localization import normalized_phrase
from .model_routing import MODEL_CATEGORIES, REASONING_EFFORT_LADDER

REQUEST_COMPLEXITY_SCHEMA_VERSION: Final[str] = "request_complexity/v1"
COMPLEXITY_MODEL_RECOMMENDATION_SCHEMA_VERSION: Final[str] = "complexity_model_recommendation/v1"

# Weakest to strongest. Order is load-bearing: consumers compare positions.
COMPLEXITY_TIERS: Final[tuple[str, ...]] = ("light", "standard", "deep")

# Inclusive lower bounds, strongest first. A score below every bound is the
# weakest tier. Thresholds and signal weights are deliberately small integers
# so a reader can add them up by hand from the payload.
COMPLEXITY_TIER_THRESHOLDS: Final[tuple[tuple[str, int], ...]] = (
    ("deep", 8),
    ("standard", 4),
)

COMPLEXITY_CLAIM_BOUNDARY: Final[str] = (
    "A complexity score is a deterministic reading of the request text and the routed skill name. "
    "It is a recommendation input, not a route, not a model choice, and not execution, review, CI, "
    "or merge evidence. omh never calls a model to produce it and never applies it without the "
    "caller declaring the dial themselves; an explicit user model or effort always wins."
)

# Message length bands, in characters of the stripped request. Long requests
# carry more scope than short ones often enough to be worth a point, and never
# more than two — length is corroboration, never a tier on its own.
COMPLEXITY_LENGTH_BANDS: Final[tuple[tuple[str, int, int], ...]] = (
    ("brief", 0, 0),
    ("medium", 200, 1),
    ("long", 600, 2),
)

# Routed-skill class weights over the capability-family vocabulary. The family
# id is OMH's own closed taxonomy for what a workflow does, so this table
# cannot drift into a parallel domain vocabulary. Families absent from the
# table weigh nothing, as does an unrouted request.
COMPLEXITY_SKILL_CLASS_WEIGHTS: Final[dict[str, int]] = {
    "delegate_coding_and_ship": 2,
    "plan_and_decide": 1,
    "operate_and_observe": 1,
    "learn_and_gather": 1,
}

# Tier -> model class. Values are members of `MODEL_CATEGORIES`, which is also
# the key vocabulary of the user's chain-override document, so a recommendation
# resolves through the user's config instead of naming a model.
COMPLEXITY_TIER_MODEL_CLASSES: Final[dict[str, str]] = {
    "light": "quick",
    "standard": "unspecified-high",
    "deep": "deep",
}

# Tier -> reasoning-effort suggestion, as rungs of `REASONING_EFFORT_LADDER`.
COMPLEXITY_TIER_EFFORTS: Final[dict[str, str]] = {
    "light": "low",
    "standard": "medium",
    "deep": "high",
}

COMPLEXITY_RECOMMENDATION_STATUSES: Final[tuple[str, ...]] = (
    "recommended",
    "superseded_by_user_override",
)

COMPLEXITY_CHAIN_STATUSES: Final[tuple[str, ...]] = (
    "resolved",
    "class_not_in_chains",
    "no_chain_config",
)

# Caps borrowed from the surveyed prior art: an extractor that counts without a
# ceiling lets one pathological paste dominate every other signal.
_MAX_COUNTED_PATHS: Final[int] = 20
_MAX_COUNTED_SUBTASKS: Final[int] = 10

_PATH_RE: Final[re.Pattern[str]] = re.compile(r"(?<![\w./-])[\w][\w./-]*/[\w./-]*\.[a-z]{1,6}(?![\w])|(?<![\w./-])[\w][\w.-]*\.(?:py|ts|tsx|js|jsx|go|rs|java|rb|md|json|yaml|yml|toml|sh|sql|css|html)(?![\w])")
_ORDERED_STEP_RE: Final[re.Pattern[str]] = re.compile(r"(?m)^\s*(?:\d+[.)]|[-*+])\s+\S")


@dataclass(frozen=True)
class ComplexitySignal:
    """One named, weighted contribution to a complexity score.

    `phrases` are matched against the accent-folded, case-folded request text
    through `normalized_phrase`, the same folding the router uses, so a signal
    cannot fire on casing or diacritics alone. Signals whose evidence is
    counted rather than phrased carry an empty `phrases` and are computed in
    `_derived_signals`.
    """

    name: str
    weight: int
    describe: str
    phrases: tuple[str, ...] = ()


# The only negative signal is `simple_request`. Everything else adds, so a
# score can be read as "how many reasons to spend more", and a trivial request
# has to earn its way up from below zero.
COMPLEXITY_SIGNALS: Final[tuple[ComplexitySignal, ...]] = (
    ComplexitySignal(
        "architecture_keywords",
        3,
        "Design-level work: the shape of the system changes, not just its lines.",
        (
            "architecture",
            "architectural",
            "rearchitect",
            "re-architect",
            "redesign",
            "restructure",
            "refactor",
            "rewrite",
            "migration",
            "migrate",
            "schema change",
            "data model",
            "design doc",
            "decouple",
        ),
    ),
    ComplexitySignal(
        "impact_system_wide",
        3,
        "Blast radius is stated as the whole surface rather than one place.",
        (
            "system-wide",
            "system wide",
            "across the codebase",
            "across the repo",
            "across every",
            "across all",
            "entire codebase",
            "entire repo",
            "whole codebase",
            "every module",
            "every service",
            "every caller",
            "all callers",
            "all services",
            "end-to-end",
            "end to end",
            "everywhere",
        ),
    ),
    ComplexitySignal(
        "risk_keywords",
        2,
        "Failure here is expensive: security, concurrency, or data-integrity work.",
        (
            "security",
            "vulnerability",
            "authentication",
            "authorization",
            "credential",
            "secret",
            "injection",
            "concurrency",
            "concurrent",
            "race condition",
            "deadlock",
            "thread safety",
            "thread-safe",
            "data loss",
            "corruption",
            "rollback",
            "backwards compatibility",
            "backward compatibility",
        ),
    ),
    ComplexitySignal(
        "debugging_keywords",
        2,
        "Investigation before repair: the cause is not yet known.",
        (
            "root cause",
            "root-cause",
            "regression",
            "stack trace",
            "traceback",
            "reproduce",
            "reproduction",
            "flaky",
            "intermittent",
            "why does it fail",
            "why is it failing",
            "bisect",
            "heisenbug",
        ),
    ),
    ComplexitySignal(
        "fanout_intent",
        2,
        "The request asks for parallel or split execution, not a single pass.",
        (
            "in parallel",
            "parallelize",
            "parallelise",
            "fanout",
            "fan out",
            "fan-out",
            "concurrently",
            "multiple agents",
            "several agents",
            "split the work",
            "split it up",
            "at the same time",
        ),
    ),
    ComplexitySignal(
        "exhaustive_search",
        4,
        "Every occurrence must be found and located exactly: recall is the task, not scope, and a small model that misses one has failed it.",
        (
            "find every",
            "find all",
            "every reference",
            "all references",
            "every usage",
            "all usages",
            "every occurrence",
            "all occurrences",
            "every call site",
            "all call sites",
            "every definition",
            "every instance of",
            "all instances of",
            "enumerate every",
            "enumerate all",
            "exhaustive",
            "exhaustively",
        ),
    ),
    ComplexitySignal(
        "simple_request",
        -2,
        "Stated as a one-liner or a lookup; the only signal that subtracts.",
        (
            "typo",
            "one-liner",
            "one liner",
            "single line",
            "one line",
            "rename",
            "bump the version",
            "bump version",
            "quick question",
            "just tell me",
            "what is",
            "what does",
            "where is",
            "print the",
            "list the files",
            "add a comment",
            "fix the spelling",
        ),
    ),
)

# Derived signals are computed, not phrase-matched, and are named here so the
# full signal vocabulary is one closed list a test can assert against.
COMPLEXITY_DERIVED_SIGNAL_NAMES: Final[tuple[str, ...]] = (
    "subtasks_many",
    "cross_file",
    "message_length",
    "routed_skill_class",
)

COMPLEXITY_SIGNAL_NAMES: Final[tuple[str, ...]] = tuple(
    [signal.name for signal in COMPLEXITY_SIGNALS] + list(COMPLEXITY_DERIVED_SIGNAL_NAMES)
)


def score_request_complexity(
    message: str,
    *,
    routed_skill: str = "",
) -> dict[str, object]:
    """Score one request and return its tier with every contributing signal named.

    `routed_skill` is a workflow name from the skill catalog; it is resolved to
    a capability-family id and weighted by class. An unknown or empty name
    contributes nothing rather than guessing.
    """
    text = str(message or "")
    folded = normalized_phrase(text)
    skill = str(routed_skill or "").strip()
    skill_class = complexity_class_for_skill(skill)

    signals: list[dict[str, object]] = []
    for signal in COMPLEXITY_SIGNALS:
        evidence = _matched_phrases(folded, signal.phrases)
        if evidence:
            signals.append(_signal_payload(signal.name, signal.weight, signal.describe, evidence))
    signals.extend(_derived_signals(text, folded, skill, skill_class))

    score = sum(int(entry["weight"]) for entry in signals)
    return {
        "schema_version": REQUEST_COMPLEXITY_SCHEMA_VERSION,
        "score": score,
        "tier": tier_for_score(score),
        "signals": signals,
        "routed_skill": skill,
        "routed_skill_class": skill_class,
        "thresholds": [{"tier": tier, "min_score": bound} for tier, bound in COMPLEXITY_TIER_THRESHOLDS],
        "claim_boundary": COMPLEXITY_CLAIM_BOUNDARY,
    }


def tier_for_score(score: int) -> str:
    """Return the tier for one score using the inclusive lower bounds."""
    for tier, bound in COMPLEXITY_TIER_THRESHOLDS:
        if score >= bound:
            return tier
    return COMPLEXITY_TIERS[0]


def complexity_class_for_skill(routed_skill: str) -> str:
    """Return the capability-family id for one workflow name, or an empty sentinel.

    The capability-family projection is imported lazily on purpose: `src/coding`
    has no import-time edge into the skill catalog today, and a scorer is not a
    reason to add one.
    """
    name = str(routed_skill or "").strip()
    if not name:
        return ""
    from ..capabilities.families import family_id_for_workflow

    return family_id_for_workflow(name)


def recommend_model_for_complexity(
    complexity: Mapping[str, object],
    *,
    chains: Mapping[str, Sequence[tuple[str, str]]] | None = None,
    requested_model: str = "",
    requested_effort: str = "",
) -> dict[str, object]:
    """Prepare the model-class recommendation for one scored request.

    `chains` is the user's effective category -> chain mapping (shipped
    defaults with `<omh-home>/routing/model-chains.json` merged over them).
    Passing `None` means no chain config was read; the class and effort are
    still reported, the concrete model is not invented.

    Effort precedence matches `model_routing`: requested effort > chain-entry
    effort > the tier suggestion. An explicit requested model or effort makes
    the whole block `superseded_by_user_override` — the recommendation is still
    disclosed so the reader can see what was set aside, never applied.
    """
    tier = str(complexity.get("tier") or COMPLEXITY_TIERS[0])
    if tier not in COMPLEXITY_TIER_MODEL_CLASSES:
        tier = COMPLEXITY_TIERS[0]
    model_class = COMPLEXITY_TIER_MODEL_CLASSES[tier]
    tier_effort = COMPLEXITY_TIER_EFFORTS[tier]

    chain_entries: list[dict[str, str]] = []
    chain_status = "no_chain_config"
    if chains is not None:
        chain_status = "class_not_in_chains"
        for model, effort in chains.get(model_class, ()) or ():
            chain_entries.append({"model": str(model), "reasoning_effort": str(effort)})
        if chain_entries:
            chain_status = "resolved"

    model = str(requested_model or "").strip()
    effort = str(requested_effort or "").strip()
    overridden = bool(model or effort)

    head = chain_entries[0] if chain_entries else {}
    resolved_effort = effort or head.get("reasoning_effort", "") or tier_effort
    resolved: dict[str, str] = {}
    if head:
        resolved = {"model": head["model"], "reasoning_effort": resolved_effort}

    payload: dict[str, object] = {
        "schema_version": COMPLEXITY_MODEL_RECOMMENDATION_SCHEMA_VERSION,
        "status": "superseded_by_user_override" if overridden else "recommended",
        "tier": tier,
        "score": int(complexity.get("score") or 0),
        "model_class": model_class,
        "reasoning_effort": resolved_effort,
        "chain_status": chain_status,
        "chain": chain_entries,
        "resolved": resolved,
        "signals": [
            {"name": entry.get("name", ""), "weight": entry.get("weight", 0)}
            for entry in _signal_entries(complexity)
        ],
        "claim_boundary": COMPLEXITY_CLAIM_BOUNDARY,
    }
    if overridden:
        payload["user_override"] = {"model": model, "reasoning_effort": effort}
        payload["override_note"] = (
            "An explicit model or reasoning effort was requested; it wins over this recommendation, "
            "which is reported for disclosure only."
        )
    return payload


def _signal_entries(complexity: Mapping[str, object]) -> list[Mapping[str, object]]:
    raw = complexity.get("signals")
    if not isinstance(raw, list):
        return []
    return [entry for entry in raw if isinstance(entry, Mapping)]


def _signal_payload(name: str, weight: int, describe: str, evidence: Sequence[str]) -> dict[str, object]:
    return {
        "name": name,
        "weight": weight,
        "describe": describe,
        "evidence": list(evidence),
    }


def _matched_phrases(folded: str, phrases: Sequence[str]) -> list[str]:
    return sorted({phrase for phrase in phrases if normalized_phrase(phrase) in folded})


def _derived_signals(text: str, folded: str, skill: str, skill_class: str) -> list[dict[str, object]]:
    signals: list[dict[str, object]] = []

    subtasks = _subtask_count(folded, text)
    if subtasks >= 3:
        signals.append(
            _signal_payload(
                "subtasks_many",
                # Weighted one point above the surveyed prior art, and this is
                # the only place we deviate. Reason: a caller who enumerated
                # three or more steps has already told us the request is more
                # than one task, which is the plainest evidence of scope this
                # scorer ever gets. It is the one signal allowed to cross the
                # `standard` boundary alone; `simple_request` still pulls a
                # list of three trivial edits back down.
                4,
                "Three or more enumerated or chained steps were requested at once.",
                [f"subtask_estimate={subtasks}"],
            )
        )

    paths = _path_count(text)
    if paths >= 2:
        signals.append(
            _signal_payload(
                "cross_file",
                2,
                "Two or more distinct files are named, so the change spans a seam.",
                [f"path_count={paths}"],
            )
        )

    band, band_weight = _length_band(text)
    if band_weight:
        signals.append(
            _signal_payload(
                "message_length",
                band_weight,
                "Longer requests carry more stated scope; length corroborates, never decides.",
                [f"length_band={band}", f"characters={len(text.strip())}"],
            )
        )

    class_weight = COMPLEXITY_SKILL_CLASS_WEIGHTS.get(skill_class, 0)
    if class_weight:
        signals.append(
            _signal_payload(
                "routed_skill_class",
                class_weight,
                "The routed skill belongs to a capability family whose work is typically heavier.",
                [f"routed_skill={skill}", f"routed_skill_class={skill_class}"],
            )
        )
    return signals


def _subtask_count(folded: str, text: str) -> int:
    """Estimate enumerated or chained steps, capped so one paste cannot dominate.

    ` then ` also covers ` and then `, which contains it, so each chained step
    is counted exactly once.
    """
    count = len(_ORDERED_STEP_RE.findall(text)) + folded.count(" then ")
    return min(count, _MAX_COUNTED_SUBTASKS)


def _path_count(text: str) -> int:
    """Count distinct file-path-shaped tokens, capped."""
    return min(len({match.casefold() for match in _PATH_RE.findall(text)}), _MAX_COUNTED_PATHS)


def _length_band(text: str) -> tuple[str, int]:
    length = len(text.strip())
    band, weight = COMPLEXITY_LENGTH_BANDS[0][0], COMPLEXITY_LENGTH_BANDS[0][2]
    for name, minimum, band_weight in COMPLEXITY_LENGTH_BANDS:
        if length >= minimum:
            band, weight = name, band_weight
    return band, weight


def _validate_module_tables() -> None:
    """Fail at import time if the tier tables leave the shared vocabularies.

    Cheap, and it means a rename in `model_routing` cannot leave this module
    quietly recommending a class or an effort rung that no longer exists.
    """
    for tier in COMPLEXITY_TIERS:
        if COMPLEXITY_TIER_MODEL_CLASSES[tier] not in MODEL_CATEGORIES:
            raise ValueError(f"model class for tier {tier!r} is not a MODEL_CATEGORIES member")
        if COMPLEXITY_TIER_EFFORTS[tier] not in REASONING_EFFORT_LADDER:
            raise ValueError(f"effort for tier {tier!r} is not a REASONING_EFFORT_LADDER rung")


_validate_module_tables()
