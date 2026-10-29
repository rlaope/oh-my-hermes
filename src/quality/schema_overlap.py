"""Prompt/schema overlap probing for the omh tool surface: a candidate is never a delete.

A tool description is paid for in every context window that loads the toolset,
and part of it is often already carried by the JSON schema sitting beside it: a
parameter's type, its enum members, its clamp range, its default, whether it is
required. Text a reader could reconstruct from `(name, schema, blank outline)`
is a **prune candidate**. It is never an automatic delete, and this module
never removes anything -- it reports.

The bucketing, which is the actual doctrine:

**Prune candidates.** Parameter names and types. `required`. Value examples
that only restate an enum. Clamp ranges already declared as `minimum` /
`maximum`.

**Keep, always.** Defaults *and their direction* -- `gitignore: true` does not
say "respects gitignore", and the schema cannot say which way the boolean
points. Routing and escalation rules. Exact output shape. Worked anti-patterns.
Constraints the type system cannot express, such as a field required only for
one action.

Three caveats travel with the bucketing, and they are why the probe reports
rather than edits:

1. **One sample is noise.** A single overlap hit is a question, not a finding.
2. **`git blame` each line before cutting it.** Much of what looks redundant is
   incident scar tissue: someone added that sentence because a model got it
   wrong once.
3. **Memorization is not inference.** A model reconstructing text from a public
   repository may be reciting it. That caveat bounds the *model-based* probe the
   upstream audit describes; this module does not run one. It matches the
   schema against its own description deterministically, which is a narrower
   question with no recitation risk -- and a correspondingly narrower answer.

So the gate here is not "no overlap". It is **every overlap is classified**:
each finding must appear in `REVIEWED_OVERLAP_DECISIONS` with a verdict and a
reason, so a new tool description that restates its schema gets a human
decision rather than sliding in unread. Self-documenting flag-style tools prune
heavily; DSL and capability tools barely -- expect most verdicts to be `keep`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

SCHEMA_OVERLAP_SCHEMA_VERSION = "omh_schema_overlap/v1"

OVERLAP_RULE_IDS = (
    "OVERLAP_BOUND_RESTATED",
    "OVERLAP_DEFAULT_RESTATED",
    "OVERLAP_ENUM_RESTATED",
    "OVERLAP_REQUIRED_RESTATED",
    "OVERLAP_TYPE_RESTATED",
)

VERDICT_PRUNE_CANDIDATE = "prune_candidate"
VERDICT_KEEP = "keep"

# Keep reasons, one per bucket the doctrine names. A finding classified `keep`
# always carries one of these, so "we looked and decided to keep it" is
# distinguishable from "nobody looked".
KEEP_REASONS = (
    "member_semantics",
    "bound_meaning",
    "default_direction",
    "conditional_requirement",
)

# A description that names every enum member is only a restatement when it
# stops there. Measured against the current tool surface: the two descriptions
# that teach what each member DOES carry 62 and 287 characters of text beyond
# the member names, while the one that merely lists them carries 35. The floor
# sits between, so "list the members" is a candidate and "say what each member
# does" is payload.
ENUM_SEMANTIC_RESIDUE_MIN_CHARS = 40

# A description is a bare type restatement when the whole of it is a type word.
_TYPE_ONLY = re.compile(
    r"\A\s*(?:an?\s+)?(?:optional\s+)?"
    r"(?:string|integer|number|boolean|bool|object|array|list|flag)\b[^.]{0,20}\.?\s*\Z",
    re.IGNORECASE,
)
# Direction: text that says what a value MEANS rather than what it IS.
_DIRECTION = re.compile(
    r"(?:=|->|\bmeans\b|\bso that\b|\brenders?\b|\bapplies\b|\bwins over\b|\bfalls? back\b"
    r"|\bdefaults? to the\b|\bhighest\b|\blowest\b|\btop-level\b|\bindent)",
    re.IGNORECASE,
)
# A requirement the type system cannot express: required only under a condition.
_CONDITIONAL = re.compile(r"\b(?:if|when|unless|only|except|for action)\b", re.IGNORECASE)
_WORDS = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True, slots=True)
class OverlapFinding:
    """One place a description restates something its schema already declares."""

    rule: str
    tool: str
    path: str
    verdict: str
    keep_reason: str
    detail: str
    excerpt: str

    @property
    def id(self) -> str:
        return f"{self.tool}.{self.path}:{self.rule}"

    def to_payload(self) -> dict[str, object]:
        return {
            "id": self.id,
            "rule": self.rule,
            "tool": self.tool,
            "path": self.path,
            "verdict": self.verdict,
            "keep_reason": self.keep_reason,
            "detail": self.detail,
            "excerpt": self.excerpt,
        }


# The reviewed verdict for every overlap the probe finds today. A finding that
# is not listed here fails the gate: the point is that somebody classified it,
# not that the count stayed the same. Each entry is `<finding id>: <reason>`.
REVIEWED_OVERLAP_DECISIONS: dict[str, str] = {
    "lsp_definition.line:OVERLAP_BOUND_RESTATED": (
        "keep — the numeral says the line is 1-based, which `minimum: 1` does not: the language "
        "server protocol the tool drives is 0-based, so a caller that read only the bound could "
        "pass an LSP line and land one line off, on symbol_not_found or the wrong symbol."
    ),
    "lsp_references.line:OVERLAP_BOUND_RESTATED": (
        "keep — the same shared `line` field as lsp_definition: 1-based is what the bound cannot "
        "say, and the LSP positions behind the tool are 0-based."
    ),
    "lsp_rename.line:OVERLAP_BOUND_RESTATED": (
        "keep — the same shared `line` field as lsp_definition; for a rename an off-by-one line "
        "picks a different symbol to rewrite across the workspace, so the 1-based statement matters most here."
    ),
    "omh_delegate_route.action:OVERLAP_ENUM_RESTATED": (
        "keep — the description says what each of set/clear/status/fallback does to the route, "
        "including that fallback advances the category chain and clears to parent inheritance "
        "when exhausted. None of that is in the enum."
    ),
    "omh_document_plan.action:OVERLAP_ENUM_RESTATED": (
        "keep — plan/show/mark are each named with what they do to the stored plan: plan writes "
        "the file and keeps an existing ledger, show re-reads, mark advances next after a covered "
        "mark. That is output shape and persistence, not member names."
    ),
    "omh_document_plan.state:OVERLAP_ENUM_RESTATED": (
        "keep — covered/next/missing carry the claim boundary the enum cannot: covered is the "
        "caller's statement rather than an observation, and marking next demotes the other next. "
        "The members alone would read as observed reading progress."
    ),
    "omh_loop.action:OVERLAP_ENUM_RESTATED": (
        "keep — each member is named with the field set it needs and what it does to "
        "loop_cycle/v2, then the text states the cross-cutting rule the members cannot "
        "carry: which actions need loop_id and expected_revision. A caller that "
        "read only the member names would omit the guard and have the write refused."
    ),
    "omh_loop.work_kind:OVERLAP_ENUM_RESTATED": (
        "keep — the two members are the enum, but the sentence carries the default. "
        "non_coding is what a loop gets when the field is omitted, and which one is the "
        "default is not visible in a member list."
    ),
    "omh_todo.action:OVERLAP_ENUM_RESTATED": (
        "keep — set/advance/clear/show are named with their effect on the stored list (set "
        "drops the items it leaves out), which is output shape, not member names. The sentence "
        "after them "
        "carries the routing rule the members cannot: a state change goes through advance, "
        "because set replaces the whole list and a caller that reaches for it to tick one item "
        "drops the ones it forgets to re-send."
    ),
    "omh_todo.item:OVERLAP_BOUND_RESTATED": (
        "keep — the numeral says the list is 1-based, which the clamp does not. `minimum: 1` "
        "is the smallest legal value and is equally true of a 0-based list whose first index "
        "is unusable; a caller that read only the bound would be off by one on every advance, "
        "and the item_text guard would refuse the write rather than explain it."
    ),
    "omh_todo.items[].depth:OVERLAP_BOUND_RESTATED": (
        "keep — the numerals carry meaning the clamp cannot: 0 is a top-level task and 1-3 render "
        "as subtasks under the preceding shallower item. Cutting them leaves a range with no "
        "semantics."
    ),
    "omh_todo.plan_stage:OVERLAP_ENUM_RESTATED": (
        "keep — the two members are the enum, and everything a caller needs is in the text "
        "around them. Which runs the field is for (a planning run, not a delivery checklist), "
        "what stamping awaiting_acceptance DOES — escalate this session's next write_file or "
        "patch to the human-approval gate — what ends it, and the lifecycle the members cannot "
        "carry: advance keeps the stamp, only set changes or drops it, and omitting the field "
        "is the default. A caller that read the member list alone would not know it was arming "
        "a gate, which is the one description here whose omission costs a person an "
        "unexplained approval prompt."
    ),
    "omh_todo.template:OVERLAP_ENUM_RESTATED": (
        "keep — the one member is the enum, and the rest is the contract the schema cannot "
        "hold: when to reach for the template, that sending no items declares the ten "
        "phases, and that a phase this change does not need is kept as done with a "
        "blocked_reason rather than dropped. A caller that read only 'code-story' would "
        "send a nine-phase list and have the write refused without knowing why. Trimmed "
        "once already — the mechanics each refusal restates verbatim at the moment it "
        "fires were cut, which is the doctrine's own 'schema and refusal already carry it' "
        "line applied to this description."
    ),
    "omh_route_answer.answered_by:OVERLAP_ENUM_RESTATED": (
        "keep — the three members are the enum, and the sentence carries what neither the "
        "member names nor the schema can: which one makes the recorded confidence "
        "self-reported, that naming the third-party plugin records a number OMH did not "
        "observe and that OMH never calls it, and that omh_jev_ask is refused without an "
        "answered ledger row for the same digest. A caller reading only the member list "
        "would read jev_plugin as an instruction to reach for one."
    ),
    "omh_jev_ask.route:OVERLAP_ENUM_RESTATED": (
        "keep — member semantics the enum cannot carry: auto's preference for the first-party "
        "route, that openrouter needs the operator setting and is not enabled by a key alone, "
        "and that a forced route never falls back. A caller reading only the members would "
        "read openrouter as available whenever an OpenRouter key exists."
    ),
    "omh_role.action:OVERLAP_ENUM_RESTATED": (
        "prune candidate — 'List available roles or read one role context.' restates list/read "
        "with only the object each acts on. Left in place pending `git blame`: it predates the "
        "role catalog split and may be scar tissue from a model calling read without a role."
    ),
}


def _text(value: object) -> str:
    return str(value or "").strip()


def _residue(description: str, members: Sequence[str]) -> int:
    lowered = description.casefold()
    for member in members:
        lowered = lowered.replace(str(member).casefold(), " ")
    return len(_WORDS.sub(" ", lowered).strip())


def _excerpt(description: str) -> str:
    single = " ".join(description.split())
    return single if len(single) <= 160 else f"{single[:157]}..."


def _finding(
    rule: str,
    tool: str,
    path: str,
    description: str,
    *,
    keep_reason: str,
    detail: str,
) -> OverlapFinding:
    return OverlapFinding(
        rule=rule,
        tool=tool,
        path=path,
        verdict=VERDICT_KEEP if keep_reason else VERDICT_PRUNE_CANDIDATE,
        keep_reason=keep_reason,
        detail=detail,
        excerpt=_excerpt(description),
    )


def _property_findings(
    tool: str,
    name: str,
    path: str,
    spec: Mapping[str, Any],
    required: Sequence[str],
) -> list[OverlapFinding]:
    description = _text(spec.get("description"))
    if not description:
        return []
    findings: list[OverlapFinding] = []

    if _TYPE_ONLY.match(description):
        findings.append(
            _finding(
                "OVERLAP_TYPE_RESTATED",
                tool,
                path,
                description,
                keep_reason="",
                detail=(
                    "the whole description is the declared type; a reader recovers it from the "
                    "schema and learns nothing else"
                ),
            )
        )

    members = [str(item) for item in spec.get("enum", []) or []]
    lowered = description.casefold()
    if members and all(member.casefold() in lowered for member in members):
        residue = _residue(description, members)
        semantic = residue >= ENUM_SEMANTIC_RESIDUE_MIN_CHARS
        findings.append(
            _finding(
                "OVERLAP_ENUM_RESTATED",
                tool,
                path,
                description,
                keep_reason="member_semantics" if semantic else "",
                detail=(
                    f"names all {len(members)} enum members with {residue} characters of text "
                    f"beyond them (floor {ENUM_SEMANTIC_RESIDUE_MIN_CHARS})"
                ),
            )
        )

    for bound in ("minimum", "maximum"):
        if bound in spec and str(spec[bound]) in description:
            findings.append(
                _finding(
                    "OVERLAP_BOUND_RESTATED",
                    tool,
                    path,
                    description,
                    keep_reason="bound_meaning" if _DIRECTION.search(description) else "",
                    detail=f"repeats the declared {bound} {spec[bound]!r}",
                )
            )
            break

    if "default" in spec and "default" in lowered and str(spec["default"]).casefold() in lowered:
        findings.append(
            _finding(
                "OVERLAP_DEFAULT_RESTATED",
                tool,
                path,
                description,
                keep_reason="default_direction" if _DIRECTION.search(description) else "",
                detail=f"repeats the declared default {spec['default']!r}",
            )
        )

    if name in required and re.search(r"\brequired\b", lowered):
        findings.append(
            _finding(
                "OVERLAP_REQUIRED_RESTATED",
                tool,
                path,
                description,
                keep_reason="conditional_requirement" if _CONDITIONAL.search(description) else "",
                detail="calls itself required for a property the schema already lists as required",
            )
        )
    return findings


def _walk(
    tool: str,
    properties: Mapping[str, Any],
    required: Sequence[str],
    prefix: str = "",
) -> list[OverlapFinding]:
    findings: list[OverlapFinding] = []
    for name in sorted(properties):
        spec = properties[name]
        if not isinstance(spec, Mapping):
            continue
        findings.extend(_property_findings(tool, name, f"{prefix}{name}", spec, required))
        nested = spec.get("properties")
        if isinstance(nested, Mapping):
            findings.extend(_walk(tool, nested, spec.get("required", []) or [], f"{prefix}{name}."))
        items = spec.get("items")
        if isinstance(items, Mapping) and isinstance(items.get("properties"), Mapping):
            findings.extend(
                _walk(tool, items["properties"], items.get("required", []) or [], f"{prefix}{name}[].")
            )
    return findings


def schema_overlap_findings(
    schemas: Sequence[Mapping[str, Any]] | None = None,
) -> list[OverlapFinding]:
    """Return every place a tool description restates its own schema."""
    if schemas is None:
        from ..plugin_bundle.omh.tools import builtin_tool_schemas

        schemas = builtin_tool_schemas()
    findings: list[OverlapFinding] = []
    for schema in schemas:
        tool = _text(schema.get("name"))
        parameters = schema.get("parameters")
        if not isinstance(parameters, Mapping):
            continue
        properties = parameters.get("properties")
        if not isinstance(properties, Mapping):
            continue
        findings.extend(_walk(tool, properties, parameters.get("required", []) or []))
    return sorted(findings, key=lambda finding: finding.id)


def unreviewed_overlap_findings(
    findings: Sequence[OverlapFinding] | None = None,
) -> list[OverlapFinding]:
    """Return findings nobody has classified yet — the gate's failure set."""
    resolved = schema_overlap_findings() if findings is None else list(findings)
    return [finding for finding in resolved if finding.id not in REVIEWED_OVERLAP_DECISIONS]


def stale_overlap_decisions(
    findings: Sequence[OverlapFinding] | None = None,
) -> list[str]:
    """Return reviewed decisions whose finding no longer exists.

    A decision left behind after its description was rewritten is a claim about
    text that is gone, so it goes when the overlap goes.
    """
    resolved = schema_overlap_findings() if findings is None else list(findings)
    live = {finding.id for finding in resolved}
    return sorted(set(REVIEWED_OVERLAP_DECISIONS) - live)


def schema_overlap_payload() -> dict[str, object]:
    findings = schema_overlap_findings()
    unreviewed = unreviewed_overlap_findings(findings)
    stale = stale_overlap_decisions(findings)
    return {
        "schema_version": SCHEMA_OVERLAP_SCHEMA_VERSION,
        "description": (
            "Deterministic overlap between omh tool descriptions and their own JSON schemas. "
            "Every finding is a prune candidate or a reviewed keep; this probe never deletes "
            "text and never runs a model."
        ),
        "ok": not unreviewed and not stale,
        "rules": list(OVERLAP_RULE_IDS),
        "keep_reasons": list(KEEP_REASONS),
        "finding_count": len(findings),
        "prune_candidate_count": sum(
            1 for finding in findings if finding.verdict == VERDICT_PRUNE_CANDIDATE
        ),
        "keep_count": sum(1 for finding in findings if finding.verdict == VERDICT_KEEP),
        "unreviewed": [finding.to_payload() for finding in unreviewed],
        "stale_decisions": stale,
        "findings": [finding.to_payload() for finding in findings],
        "claim_boundary": (
            "A prune candidate is a question for a reviewer, never an automatic delete. "
            "`git blame` the line first: much of what restates a schema is incident scar tissue."
        ),
    }


def format_schema_overlap_report(payload: Mapping[str, object]) -> str:
    """Render the probe as a paste-ready review report."""
    lines = [
        f"omh tool prompt/schema overlap: {payload.get('finding_count', 0)} finding(s), "
        f"{payload.get('prune_candidate_count', 0)} prune candidate(s), "
        f"{payload.get('keep_count', 0)} reviewed keep(s)."
    ]
    for finding in payload.get("findings", []):  # type: ignore[union-attr]
        verdict = str(finding["verdict"])
        reason = f" ({finding['keep_reason']})" if finding["keep_reason"] else ""
        lines.append(f"  [{finding['rule']}] {finding['tool']}.{finding['path']} -> {verdict}{reason}")
        lines.append(f"    {finding['detail']}")
        lines.append(f"    > {finding['excerpt']}")
    unreviewed = list(payload.get("unreviewed", []))  # type: ignore[arg-type]
    if unreviewed:
        lines.append(
            f"  {len(unreviewed)} finding(s) have no reviewed verdict. Add each id to "
            "REVIEWED_OVERLAP_DECISIONS in src/quality/schema_overlap.py with either "
            "'keep — <which bucket>' or 'prune candidate — <what git blame showed>':"
        )
        for finding in unreviewed:
            lines.append(f"    {finding['id']}")
    for stale in payload.get("stale_decisions", []):  # type: ignore[union-attr]
        lines.append(f"  stale decision, its overlap is gone: {stale}")
    lines.append(
        "  Prune candidate is never an automatic delete. Keep defaults and their direction, "
        "routing rules, exact output shape, worked anti-patterns, and type-invisible constraints."
    )
    return "\n".join(lines)


__all__ = [
    "ENUM_SEMANTIC_RESIDUE_MIN_CHARS",
    "KEEP_REASONS",
    "OVERLAP_RULE_IDS",
    "REVIEWED_OVERLAP_DECISIONS",
    "SCHEMA_OVERLAP_SCHEMA_VERSION",
    "VERDICT_KEEP",
    "VERDICT_PRUNE_CANDIDATE",
    "OverlapFinding",
    "format_schema_overlap_report",
    "schema_overlap_findings",
    "schema_overlap_payload",
    "stale_overlap_decisions",
    "unreviewed_overlap_findings",
]
