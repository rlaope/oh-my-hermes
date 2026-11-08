"""Per-skill instruction density for the catalog-rendered skill bodies.

`FULL_PROFILE_SKILL_BODY_CHAR_LIMIT` already bounds how many bytes the whole
generated pack costs. It cannot tell a body that grew because a workflow gained
a rule from a body that grew because someone wrote three sentences where one
carried the instruction. This module measures the second thing: how much of a
skill body is payload a reader would act on.

Three signals, measured on the catalog producer (`builtin_skill_templates()`),
never on the committed `skills/*/SKILL.md` copies:

- ``filler_hits``: occurrences of the reviewed `FILLER_PHRASES` list. Each entry
  is a connective that can be deleted without losing a claim, a bound, or a
  condition.
- ``repeated_share_percent``: the share of a body's own sentence characters
  spent on the second and later copies of a sentence it already contains. This
  is intra-skill repetition; cross-skill repetition is a different cost and is
  already reported by `skills.context_cost`.
- ``payload_markers_per_1k``: never-delete payload per 1,000 prose characters.
  The marker list is the floor, not a style preference -- RFC 2119 modals,
  negation and exception words, conditionals, numeric bounds, and exact strings
  (identifiers, flags, paths) are the parts of an instruction that change what
  a reader does. Prose carrying few of them per character is prose that is
  describing rather than instructing.

Two surfaces are excluded from the prose on purpose. The frontmatter
`description` and the "Strong routing signals" list are *retrieval* surface:
they are matched against the user's own phrasing by `src/routing/`, so
keyword-redundant alternatives are payload there even where a human reader
needs only one. The body compresses; the trigger never does.
`compression_verdict()` enforces the same split for a proposed rewrite.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from ..skills.context_cost import CHARS_PER_TOKEN_ESTIMATE

SKILL_DENSITY_SCHEMA_VERSION = "omh_skill_density/v1"

SKILL_DENSITY_RULE_IDS = (
    "SKILL_DENSITY_FILLER",
    "SKILL_DENSITY_PAYLOAD_FLOOR",
    "SKILL_DENSITY_REPEATED_CONTENT",
)

# Reviewed list. Every entry is a phrase whose deletion leaves the surrounding
# claim intact, so a hit is a character an install pays for in every context
# window without changing what a reader does. Keep it short and arguable-free:
# a phrase that sometimes carries meaning ("note that", "make sure") does not
# belong here, because a gate nobody trusts gets exempted rather than fixed.
FILLER_PHRASES: tuple[str, ...] = (
    "as mentioned above",
    "as mentioned earlier",
    "as you can see",
    "at the end of the day",
    "at this point in time",
    "basically",
    "due to the fact that",
    "each and every",
    "first and foremost",
    "for the purpose of",
    "in order to",
    "in terms of",
    "in the event that",
    "it goes without saying",
    "it is important to note",
    "it should be noted",
    "keep in mind that",
    "needless to say",
    "please note",
    "simply put",
    "the fact that",
    "with regard to",
    "with respect to",
)

# The never-delete payload list, in match order. `exact_string` runs first so a
# backticked flag such as `--limit 3` counts once as one exact string rather
# than twice as a string plus a bound.
PAYLOAD_MARKER_PATTERNS: tuple[tuple[str, str], ...] = (
    ("exact_string", r"`[^`\n]+`"),
    ("modal", r"\b(?:must|shall|should|may|required|requires|never|always|only)\b"),
    ("negation", r"\b(?:not|no|none|without|except|unless|neither|cannot|avoid|refuse)\b"),
    ("conditional", r"\b(?:if|when|before|after|until|while|otherwise|instead)\b"),
    ("bound", r"\d+(?:\.\d+)?%?"),
)

# A sentence shorter than this is a structural label ("Good example:", "Why:"),
# not content, and counting those as repetition would flag the rendered skill
# shape rather than the prose an author wrote.
REPEATED_SENTENCE_MIN_CHARS = 40

# Thresholds. See `tests/test_skill_density.py` for the measured distribution
# they were set from and for what each one buys.
DENSITY_FILLER_HIT_CEILING = 0
DENSITY_REPEATED_SHARE_CEILING_PERCENT = 5.0
# 9.0 -> 7.9, the same about 10% below the measured worst case: each body's lane line dropped a sample of up to
# eight backticked sibling names that did not load, which the marker count had read as payload. That leaves
# `meeting-brief` the worst at 8.79; its prose did not change.
DENSITY_PAYLOAD_MARKERS_PER_1K_FLOOR = 7.9

# Named exemptions with a reason each, never a silent skip. Empty today: the
# thresholds above were set from the measured corpus so that no skill needs
# one. A new entry is a review decision, not a way past a red gate.
DENSITY_REVIEWED_EXEMPTIONS: dict[str, str] = {}

# A compression pass whose measured token delta is under this keeps the
# original. On already-dense text the remaining words are the payload, and a
# rewrite that trades a single-digit percentage for a re-read of every rule is
# a bad trade even when nothing is lost.
COMPRESSION_KEEP_ORIGINAL_DELTA_PERCENT = 10.0

_FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)
_ROUTING_SIGNALS_LINE = re.compile(r"^[ \t]*Strong routing signals:.*$", re.MULTILINE)
_FILLER_RE = re.compile(
    "|".join(rf"\b{re.escape(phrase)}\b" for phrase in FILLER_PHRASES), re.IGNORECASE
)
_PAYLOAD_RE = re.compile(
    "|".join(f"(?P<{name}>{pattern})" for name, pattern in PAYLOAD_MARKER_PATTERNS),
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class SkillDensityMeasurement:
    skill: str
    prose_chars: int
    filler_hits: int
    filler_excerpts: tuple[str, ...]
    repeated_share_percent: float
    repeated_excerpts: tuple[str, ...]
    payload_markers: int
    payload_markers_per_1k: float

    def to_payload(self) -> dict[str, object]:
        return {
            "skill": self.skill,
            "prose_chars": self.prose_chars,
            "filler_hits": self.filler_hits,
            "filler_excerpts": list(self.filler_excerpts),
            "repeated_share_percent": self.repeated_share_percent,
            "repeated_excerpts": list(self.repeated_excerpts),
            "payload_markers": self.payload_markers,
            "payload_markers_per_1k": self.payload_markers_per_1k,
        }


def trigger_surface(content: str) -> str:
    """Return the retrieval surface of a rendered body: frontmatter + signals.

    This is the text a compression pass may never touch. It is returned as one
    string so a before/after comparison is a single equality check.
    """
    frontmatter = _FRONTMATTER.match(content)
    head = frontmatter.group(0) if frontmatter is not None else ""
    signals = "\n".join(match.strip() for match in _ROUTING_SIGNALS_LINE.findall(content))
    return f"{head}{signals}"


def instruction_prose(content: str) -> str:
    """Return the compressible part of a rendered body.

    Frontmatter and the routing-signal list are removed, because both are
    matched against user phrasing rather than read as instructions.
    """
    return _ROUTING_SIGNALS_LINE.sub("", _FRONTMATTER.sub("", content))


def _sentence_units(prose: str) -> list[str]:
    units: list[str] = []
    for line in prose.splitlines():
        stripped = line.strip().lstrip("-*# ").strip()
        if not stripped:
            continue
        for part in _SENTENCE_SPLIT.split(stripped):
            normalized = re.sub(r"\s+", " ", part).strip().lower()
            if len(normalized) >= REPEATED_SENTENCE_MIN_CHARS:
                units.append(normalized)
    return units


def payload_markers(text: str) -> Counter[str]:
    """Count never-delete markers as `category:matched-text` keys.

    The key keeps the matched text so a before/after difference names the exact
    claim, bound, or identifier a rewrite dropped instead of only how many.

    Filler spans are blanked first. "It should be noted" carries an RFC 2119
    modal by accident, and counting it would both flatter a wordy body's
    density and make deleting the filler look like a payload loss.
    """
    found: Counter[str] = Counter()
    for match in _PAYLOAD_RE.finditer(_FILLER_RE.sub(" ", text)):
        name = match.lastgroup or "payload"
        found[f"{name}:{match.group(0).strip().lower()}"] += 1
    return found


def _excerpt(prose: str, start: int, end: int) -> str:
    line_start = prose.rfind("\n", 0, start) + 1
    line_end = prose.find("\n", end)
    line = prose[line_start : line_end if line_end != -1 else len(prose)].strip()
    return line if len(line) <= 160 else f"{line[:157]}..."


def measure_skill_density(skill: str, content: str) -> SkillDensityMeasurement:
    prose = instruction_prose(content)
    prose_chars = len(prose)

    filler_matches = list(_FILLER_RE.finditer(prose))
    filler_excerpts = tuple(
        dict.fromkeys(_excerpt(prose, match.start(), match.end()) for match in filler_matches)
    )[:3]

    units = _sentence_units(prose)
    counts = Counter(units)
    unit_chars = sum(len(unit) * total for unit, total in counts.items())
    repeated_chars = sum(len(unit) * (total - 1) for unit, total in counts.items() if total > 1)
    repeated_excerpts = tuple(
        unit if len(unit) <= 160 else f"{unit[:157]}..."
        for unit, total in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        if total > 1
    )[:3]

    markers = sum(payload_markers(prose).values())
    return SkillDensityMeasurement(
        skill=skill,
        prose_chars=prose_chars,
        filler_hits=len(filler_matches),
        filler_excerpts=filler_excerpts,
        repeated_share_percent=round(repeated_chars * 100 / unit_chars, 2) if unit_chars else 0.0,
        repeated_excerpts=repeated_excerpts,
        payload_markers=markers,
        payload_markers_per_1k=round(markers * 1000 / prose_chars, 2) if prose_chars else 0.0,
    )


def skill_density_measurements() -> list[SkillDensityMeasurement]:
    from ..skills.packaging import builtin_skill_templates

    return [
        measure_skill_density(template.name, template.content)
        for template in sorted(builtin_skill_templates(), key=lambda item: item.name)
    ]


def _violation(
    rule: str,
    measurement: SkillDensityMeasurement,
    measured: float,
    threshold: float,
    detail: str,
    excerpts: tuple[str, ...],
) -> dict[str, object]:
    return {
        "rule": rule,
        "skill": measurement.skill,
        "measured": measured,
        "threshold": threshold,
        "detail": detail,
        "excerpts": list(excerpts),
    }


def skill_density_violations(
    measurements: list[SkillDensityMeasurement] | None = None,
) -> list[dict[str, object]]:
    """Return every threshold breach, exemptions applied by name."""
    resolved = skill_density_measurements() if measurements is None else measurements
    found: list[dict[str, object]] = []
    for measurement in resolved:
        if measurement.skill in DENSITY_REVIEWED_EXEMPTIONS:
            continue
        if measurement.filler_hits > DENSITY_FILLER_HIT_CEILING:
            found.append(
                _violation(
                    "SKILL_DENSITY_FILLER",
                    measurement,
                    measurement.filler_hits,
                    DENSITY_FILLER_HIT_CEILING,
                    f"{measurement.filler_hits} reviewed filler phrase(s) in the SKILL.md body; "
                    "delete the phrase and keep the claim",
                    measurement.filler_excerpts,
                )
            )
        if measurement.repeated_share_percent > DENSITY_REPEATED_SHARE_CEILING_PERCENT:
            found.append(
                _violation(
                    "SKILL_DENSITY_REPEATED_CONTENT",
                    measurement,
                    measurement.repeated_share_percent,
                    DENSITY_REPEATED_SHARE_CEILING_PERCENT,
                    f"{measurement.repeated_share_percent}% of this body's sentence characters are "
                    "second-and-later copies of its own sentences; keep one copy or move the shared "
                    "text to a reference",
                    measurement.repeated_excerpts,
                )
            )
        if measurement.payload_markers_per_1k < DENSITY_PAYLOAD_MARKERS_PER_1K_FLOOR:
            found.append(
                _violation(
                    "SKILL_DENSITY_PAYLOAD_FLOOR",
                    measurement,
                    measurement.payload_markers_per_1k,
                    DENSITY_PAYLOAD_MARKERS_PER_1K_FLOOR,
                    f"{measurement.payload_markers} never-delete markers across "
                    f"{measurement.prose_chars} prose chars; the body describes more than it "
                    "instructs -- state the rule, the bound, or the exact string, or cut the prose",
                    (),
                )
            )
    return found


def catalog_filler_hit_total() -> int:
    return sum(measurement.filler_hits for measurement in skill_density_measurements())


def _distribution(values: list[float]) -> dict[str, float]:
    ordered = sorted(values)
    if not ordered:
        return {"count": 0, "min": 0.0, "median": 0.0, "max": 0.0}
    return {
        "count": len(ordered),
        "min": ordered[0],
        "median": ordered[len(ordered) // 2],
        "max": ordered[-1],
    }


def skill_density_payload() -> dict[str, object]:
    measurements = skill_density_measurements()
    violations = skill_density_violations(measurements)
    return {
        "schema_version": SKILL_DENSITY_SCHEMA_VERSION,
        "description": (
            "Per-skill instruction density for catalog-rendered skill bodies. Frontmatter and the "
            "routing-signal list are excluded as retrieval surface. Token figures elsewhere in this "
            "repo use a chars/4 estimate, not tokenizer output."
        ),
        "ok": not violations,
        "rules": list(SKILL_DENSITY_RULE_IDS),
        "thresholds": {
            "filler_hit_ceiling": DENSITY_FILLER_HIT_CEILING,
            "repeated_share_ceiling_percent": DENSITY_REPEATED_SHARE_CEILING_PERCENT,
            "payload_markers_per_1k_floor": DENSITY_PAYLOAD_MARKERS_PER_1K_FLOOR,
        },
        "reviewed_exemptions": dict(DENSITY_REVIEWED_EXEMPTIONS),
        "skill_count": len(measurements),
        "distribution": {
            "filler_hits": _distribution([float(item.filler_hits) for item in measurements]),
            "repeated_share_percent": _distribution([item.repeated_share_percent for item in measurements]),
            "payload_markers_per_1k": _distribution([item.payload_markers_per_1k for item in measurements]),
        },
        "violations": violations,
        "skills": [measurement.to_payload() for measurement in measurements],
    }


def format_skill_density_violations(violations: list[dict[str, object]]) -> str:
    """Render violations as a paste-ready failure message."""
    if not violations:
        return ""
    lines = [f"{len(violations)} skill density violation(s):"]
    for finding in violations:
        lines.append(
            f"  [{finding['rule']}] {finding['skill']}: measured {finding['measured']}, "
            f"threshold {finding['threshold']}"
        )
        lines.append(f"    {finding['detail']}")
        for excerpt in finding["excerpts"]:  # type: ignore[union-attr]
            lines.append(f"    > {excerpt}")
    lines.append(
        "  Thresholds and the reviewed exemption list live in src/quality/skill_density.py; "
        "the authoring doctrine is docs/ADDING-A-SKILL.md."
    )
    return "\n".join(lines)


def compression_verdict(skill: str, before: str, after: str) -> dict[str, object]:
    """Judge a proposed rewrite of one rendered skill body.

    The verdict says `keep_original` when the rewrite is not worth its risk:
    the measured token delta is under `COMPRESSION_KEEP_ORIGINAL_DELTA_PERCENT`,
    the rewrite touched the retrieval surface, or it dropped never-delete
    payload. `dropped_payload` is the declared-loss list -- every claim, bound,
    or exact string present before and missing after, named rather than
    counted, because an undeclared loss is a silent regression.
    """
    before_prose = instruction_prose(before)
    after_prose = instruction_prose(after)
    before_tokens = -(-len(before_prose) // CHARS_PER_TOKEN_ESTIMATE)
    after_tokens = -(-len(after_prose) // CHARS_PER_TOKEN_ESTIMATE)
    delta_percent = (
        round((before_tokens - after_tokens) * 100 / before_tokens, 2) if before_tokens else 0.0
    )
    dropped = payload_markers(before_prose) - payload_markers(after_prose)
    trigger_changed = trigger_surface(before) != trigger_surface(after)

    reasons: list[str] = []
    if trigger_changed:
        reasons.append(
            "the rewrite changed the retrieval surface (frontmatter description or routing "
            "signals); the body compresses, the trigger never does"
        )
    if dropped:
        reasons.append(
            "the rewrite dropped never-delete payload: "
            + ", ".join(sorted(dropped.elements()))
        )
    if delta_percent < COMPRESSION_KEEP_ORIGINAL_DELTA_PERCENT:
        reasons.append(
            f"measured delta {delta_percent}% is under the "
            f"{COMPRESSION_KEEP_ORIGINAL_DELTA_PERCENT}% floor; on already-dense text the "
            "remaining words are the payload"
        )
    return {
        "schema_version": SKILL_DENSITY_SCHEMA_VERSION,
        "skill": skill,
        "verdict": "keep_original" if reasons else "accept_draft",
        "before_estimated_tokens": before_tokens,
        "after_estimated_tokens": after_tokens,
        "delta_percent": delta_percent,
        "trigger_changed": trigger_changed,
        "dropped_payload": sorted(dropped.elements()),
        "reasons": reasons,
        "before": measure_skill_density(skill, before).to_payload(),
        "after": measure_skill_density(skill, after).to_payload(),
    }
