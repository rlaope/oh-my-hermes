"""ULW contract-equivalence gate for the `ulw-work` fold (issue #954, PR D).

Four retiring engine contracts -- `team`, `ultraprocess`, `ralph`, and
`ultragoal` -- fold into `ultrawork` as four named internal capabilities.
This module is the evidence machinery that proves every counted obligation of
each retiring contract has a surviving carrier in `ultrawork`'s **rendered**
`SKILL.md`, the byte-gated artifact that `docs workflows --check` and the
tap-skills staleness check compare.

Method (plan §8.2): mutation-sensitive, structurally-scoped,
reason-code-isolated presence testing against the rendered contract. A carrier
is structural, not a substring grep: the obligation must appear under its
declared rendered section **and** inside its capability's tagged block
(`[capability:<id>]` markers in the rendered text). Mutants are introduced at
the `SkillDefinition` level and re-rendered through
`omh.skills.render.workflow_skill_from_definition` -- never by editing a dict
or monkeypatching the cached catalog.

Obligation classes (plan §8.2.1):

- ``unique``            -- counted; removal mutant must fail with exactly its
                           reason code.
- ``shared_with``       -- counted once, attributed to the named sibling
                           contracts; the mutant assertion is set-equality
                           against the declared shared failure set. For both
                           shared obligations in this table the declared set is
                           the obligation's own code: the sibling's equivalent
                           duty is carried by a distinct line that the mutant
                           does not touch, so removal fires exactly one code.
- ``pre_existing_in_target`` -- excluded; already satisfied by `ultrawork` as
                           rendered on `main` before the fold (satisfaction
                           beats uniqueness -- the tie-break).
- ``dissolves_on_fold`` -- excluded; a sibling boundary whose named target is
                           itself folding. Admissible only when the named
                           target is one of the five fold members; the
                           boundary must be rewritten, not merely dropped.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Mapping

CONTRACT_EQUIVALENCE_SCHEMA_VERSION = "omh_ulw_contract_equivalence/v1"

OBLIGATION_CLASSES = ("unique", "shared_with", "pre_existing_in_target", "dissolves_on_fold")
_EXCLUDED_CLASSES = {"pre_existing_in_target", "dissolves_on_fold"}

ULW_FOLD_CAPABILITIES = (
    "coordinated_scope",
    "delivery_boundary",
    "single_owner_persistence",
    "durable_checkpoint",
)

# Admission rule for `dissolves_on_fold` (plan §8.2.1): the four folding
# contracts plus the fold target. A boundary naming a retained skill (for
# example `loop`) is ineligible, full stop.
DISSOLVES_ADMISSIBLE_TARGETS = frozenset({"team", "ralph", "ultragoal", "ultraprocess", "ultrawork"})

_CAPABILITY_TAG_PATTERN = re.compile(r"\[capability:([a-z_]+)\]")
_HEADING_PATTERN = re.compile(r"^## (.+)$")
_METADATA_LABEL_PATTERN = re.compile(r"^([A-Z][A-Za-z /-]*):$")

# Cues used only to pin each retiring contract's live routing decision inside
# its source projection. Routing itself is untouched by PR D.
_SOURCE_PROJECTION_CUES = {
    "team": "run three coordinated workers on one shared task list",
    "ultraprocess": "single-cycle delivery",
    "ralph": "finish until done",
    "ultragoal": "durable goal",
}

_SOURCE_PROJECTION_FIELDS = (
    "safety_rules",
    "quality_bar",
    "final_checklist",
    "recovery_notes",
    "required_inputs",
    "expected_outputs",
    "do_not_use_when",
    "artifact_expectations",
    "handoff_policy",
)


@dataclass(frozen=True)
class SectionRequirement:
    """One rendered section the obligation's carrier must appear in."""

    section: str
    fragments: tuple[str, ...]


@dataclass(frozen=True)
class CarriedEntry:
    """The exact `ultrawork` definition entry that carries the obligation."""

    definition_field: str
    text: str


@dataclass(frozen=True)
class ObligationCarrier:
    obligation_id: str
    source_field: str
    source_quote: str
    obligation_class: str
    shared_with: tuple[str, ...]
    reason_code: str
    requirements: tuple[SectionRequirement, ...]
    carried: tuple[CarriedEntry, ...] = ()
    notes: str = ""

    @property
    def target_section(self) -> str:
        return self.requirements[0].section

    def carried_in(self, rendered: "RenderedContract", capability: str) -> bool:
        """Structural carrier check: section AND capability block, per line."""
        tag = f"[capability:{capability}]"
        for requirement in self.requirements:
            lines = rendered.section_lines.get(requirement.section, ())
            if not any(
                tag in line and all(fragment in line for fragment in requirement.fragments)
                for line in lines
            ):
                return False
        return True

    def satisfied_without_capability_block(self, rendered: "RenderedContract") -> bool:
        """Tag-agnostic satisfaction check used by the tie-break and the
        `pre_existing_in_target` pin against the pre-fold fixture."""
        for requirement in self.requirements:
            lines = rendered.section_lines.get(requirement.section, ())
            if not any(
                all(fragment in line for fragment in requirement.fragments) for line in lines
            ):
                return False
        return True


@dataclass(frozen=True)
class RenderedContract:
    """The rendered SKILL.md parsed into headings and capability blocks."""

    raw: str
    sections: Mapping[str, str]
    capability_blocks: Mapping[str, str]
    section_lines: Mapping[str, tuple[str, ...]] = field(default_factory=dict)


def parse_contract(raw: str) -> RenderedContract:
    """Parse a rendered SKILL.md into sections and capability blocks.

    Sections are the `## ` markdown headings; inside `Catalog Metadata` the
    plain `Label:` sub-blocks (`Quality bar:`, `Safety rules:`, ...) become
    sections of their own, keyed by label, because that is where the catalog
    fields render. Capability blocks are the lines tagged
    `[capability:<id>]`, wherever they appear.
    """
    section_lines: dict[str, list[str]] = {}
    current_section = ""
    metadata_label = ""
    in_metadata = False
    for line in raw.splitlines():
        heading = _HEADING_PATTERN.match(line)
        if heading:
            current_section = heading.group(1).strip()
            in_metadata = current_section == "Catalog Metadata"
            metadata_label = ""
            section_lines.setdefault(current_section, [])
            continue
        if in_metadata:
            label = _METADATA_LABEL_PATTERN.match(line.strip())
            if label:
                metadata_label = label.group(1).strip()
                section_lines.setdefault(metadata_label, [])
                continue
        key = metadata_label if (in_metadata and metadata_label) else current_section
        if key:
            section_lines.setdefault(key, []).append(line)
    capability_blocks: dict[str, list[str]] = {capability: [] for capability in ULW_FOLD_CAPABILITIES}
    for line in raw.splitlines():
        for match in _CAPABILITY_TAG_PATTERN.finditer(line):
            capability = match.group(1)
            if capability in capability_blocks and line not in capability_blocks[capability]:
                capability_blocks[capability].append(line)
    return RenderedContract(
        raw=raw,
        sections={name: "\n".join(lines) for name, lines in section_lines.items()},
        capability_blocks={name: "\n".join(lines) for name, lines in capability_blocks.items()},
        section_lines={name: tuple(lines) for name, lines in section_lines.items()},
    )


def rendered_target_contract() -> RenderedContract:
    """The ultrawork SKILL.md exactly as `builtin_skill_templates()` renders it."""
    from ..skills.packaging import builtin_skill_templates

    for template in builtin_skill_templates():
        if template.name == "ultrawork":
            return parse_contract(template.content)
    raise KeyError("ultrawork template missing from builtin_skill_templates()")


@dataclass(frozen=True)
class ContractEquivalenceCase:
    contract_id: str
    target_capability: str
    baseline_digest: str
    obligations: tuple[ObligationCarrier, ...]

    def counted_obligations(self) -> tuple[ObligationCarrier, ...]:
        return tuple(
            obligation
            for obligation in self.obligations
            if obligation.obligation_class not in _EXCLUDED_CLASSES
        )

    def excluded_obligations(self) -> tuple[ObligationCarrier, ...]:
        return tuple(
            obligation
            for obligation in self.obligations
            if obligation.obligation_class in _EXCLUDED_CLASSES
        )

    def shared_failure_set(self, obligation: ObligationCarrier) -> frozenset[str]:
        """The declared reason-code set a mutant of this obligation must fire.

        Both `shared_with` obligations in this table keep a single-carrier
        line whose sibling duty is satisfied by a distinct pre-existing target
        line, so the declared set is the obligation's own reason code. The
        declaration is explicit so an over-broad gate that fires extra codes
        still fails set-equality.
        """
        return frozenset({obligation.reason_code})


def _canonical_digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def source_contract_projection(contract_id: str) -> dict[str, object]:
    """Recompute one retiring contract's source projection from live producers.

    Covers the plan §8.1 field list plus the primary harness and the live
    routing decision for a representative cue. The four retiring definitions
    are untouched during PR D, so the digest of this projection must match the
    frozen baseline captured on `main` before the fold.
    """
    from ..skills.catalog import primary_harness_for_skill
    from ..skills.render import _definitions_by_name
    from ..wrapper.contract import build_chat_interaction_payload

    if contract_id not in _SOURCE_PROJECTION_CUES:
        raise KeyError(f"unknown retiring contract: {contract_id}")
    definition = _definitions_by_name()[contract_id]
    cue = _SOURCE_PROJECTION_CUES[contract_id]
    interaction = build_chat_interaction_payload(cue, source="discord")
    route = interaction.get("route") if isinstance(interaction.get("route"), dict) else {}
    fields: dict[str, object] = {}
    for field_name in _SOURCE_PROJECTION_FIELDS:
        value = getattr(definition, field_name)
        fields[field_name] = list(value) if isinstance(value, tuple) else value
    return {
        "schema_version": CONTRACT_EQUIVALENCE_SCHEMA_VERSION,
        "contract_id": contract_id,
        "definition": fields,
        "primary_harness": primary_harness_for_skill(contract_id),
        "routing": {
            "message": cue,
            "route_action": route.get("action"),
            "selected_workflow": route.get("selected_skill"),
            "next_action": interaction.get("next_action"),
        },
    }


def source_contract_digest(contract_id: str) -> str:
    return _canonical_digest(source_contract_projection(contract_id))


def evaluate_contract_equivalence(contract_id: str, rendered: RenderedContract) -> dict[str, object]:
    case = contract_equivalence_case(contract_id)
    failures: list[str] = []
    excluded: list[str] = []
    for obligation in case.obligations:
        if obligation.obligation_class in _EXCLUDED_CLASSES:
            excluded.append(obligation.obligation_id)
            continue
        if not obligation.carried_in(rendered, case.target_capability):
            failures.append(obligation.reason_code)
    return {
        "schema_version": CONTRACT_EQUIVALENCE_SCHEMA_VERSION,
        "contract_id": contract_id,
        "target_capability": case.target_capability,
        "ok": not failures,
        "failures": failures,
        "excluded": excluded,
    }


def contract_equivalence_case(contract_id: str) -> ContractEquivalenceCase:
    for case in CONTRACT_EQUIVALENCE_CASES:
        if case.contract_id == contract_id:
            return case
    raise KeyError(f"unknown retiring contract: {contract_id}")


def dissolves_on_fold_members() -> tuple[dict[str, str], ...]:
    """Both reciprocal boundaries that become vacuous when the contracts merge.

    The member list is pinned by `tests/test_ulw_equivalence.py` against a
    checked-in expectation and validated against the admission rule, so a
    boundary naming a retained skill cannot be smuggled into the excluded
    class.
    """
    return (
        {
            "member_id": "team.ultrawork_boundary",
            "named_target": "ultrawork",
            "source": "team.do_not_use_when",
            "evidence": (
                "An accepted implementation plan with disjoint files, criteria, and commands is "
                "ready for parallel delivery; use `ultrawork`."
            ),
        },
        {
            "member_id": "ultrawork.team_boundary",
            "named_target": "team",
            "source": "ultrawork.do_not_use_when",
            "evidence": (
                "The lanes are exploratory research or QA coordination without an accepted "
                "implementation plan; use `team`."
            ),
            "rewritten_reference": "coordinated_scope",
        },
    )


# The four capability selection cards. One line each, executor-neutral by
# construction: `ulw-work` capability selection never chooses a coding owner.
_CAPABILITY_SELECTION = {
    "coordinated_scope": (
        "Coordinated worker lanes with explicit ownership, collision prevention, and integrated "
        "lane status."
    ),
    "delivery_boundary": (
        "One bounded plan-to-PR delivery cycle with research-first ordering, review and docs "
        "gates, and a hard stop."
    ),
    "single_owner_persistence": (
        "One owner finishes a concrete task through implementation and verification until the "
        "gate passes."
    ),
    "durable_checkpoint": (
        "Durable goal ledger with checkpointed progress, resume points, and a final completion "
        "gate."
    ),
}

_CAPABILITY_CLAIM_BOUNDARY = (
    "Selecting a capability is routing guidance only; it is not execution, implementation, "
    "review, CI, merge, or delivery evidence, and it never chooses a coding owner."
)


def ulw_work_capability_projection(capability_id: str) -> Mapping[str, object]:
    """Project one `ulw-work` capability from the equivalence case table.

    Derived from the same `ContractEquivalenceCase` rows the carriers read, so
    the gate and this projection cannot disagree about which obligations
    belong to which capability. Raises `KeyError` for an unknown id; there is
    no default.
    """
    for case in CONTRACT_EQUIVALENCE_CASES:
        if case.target_capability == capability_id:
            counted = case.counted_obligations()
            return {
                "capability_id": capability_id,
                "source_contract": case.contract_id,
                "obligations": tuple(obligation.obligation_id for obligation in counted),
                "reason_codes": tuple(obligation.reason_code for obligation in counted),
                "selection": {
                    "capability_reason": _CAPABILITY_SELECTION[capability_id],
                    "claim_boundary": _CAPABILITY_CLAIM_BOUNDARY,
                },
            }
    raise KeyError(f"unknown ulw-work capability: {capability_id}")


def external_cli_profile_leaks(payload: object, path: str = "$") -> list[str]:
    """Paths in a recursively flattened payload that mention an external CLI.

    Checks values and keys, so a profile smuggled into a nested reason string
    or an unexpected `selected_executor_profile` key is caught wherever it
    hides.
    """
    from ..coding.executors import EXTERNAL_CLI_PROFILES

    leaks: list[str] = []
    if isinstance(payload, Mapping):
        for key, value in payload.items():
            key_text = str(key)
            if key_text == "selected_executor_profile":
                leaks.append(f"{path}.{key_text}")
            leaks.extend(external_cli_profile_leaks(key_text, f"{path}.{key_text}<key>"))
            leaks.extend(external_cli_profile_leaks(value, f"{path}.{key_text}"))
        return leaks
    if isinstance(payload, (list, tuple, set, frozenset)):
        for index, value in enumerate(payload):
            leaks.extend(external_cli_profile_leaks(value, f"{path}[{index}]"))
        return leaks
    text = str(payload).casefold()
    for profile in EXTERNAL_CLI_PROFILES:
        if profile.casefold() in text:
            leaks.append(path)
            break
    return leaks


def _obligation(
    obligation_id: str,
    source_field: str,
    source_quote: str,
    obligation_class: str,
    reason_code: str,
    requirements: tuple[SectionRequirement, ...],
    *,
    shared_with: tuple[str, ...] = (),
    carried: tuple[CarriedEntry, ...] = (),
    notes: str = "",
) -> ObligationCarrier:
    if obligation_class not in OBLIGATION_CLASSES:
        raise ValueError(f"unknown obligation class: {obligation_class}")
    if (obligation_class == "shared_with") != bool(shared_with):
        raise ValueError(f"shared_with must be set exactly for shared obligations: {obligation_id}")
    return ObligationCarrier(
        obligation_id=obligation_id,
        source_field=source_field,
        source_quote=source_quote,
        obligation_class=obligation_class,
        shared_with=shared_with,
        reason_code=reason_code,
        requirements=requirements,
        carried=carried,
        notes=notes,
    )


_TEAM_OBLIGATIONS = (
    _obligation(
        "team.lane_independence",
        "safety_rules",
        "Use parallel lanes only when work is independent.",
        "unique",
        "missing_lane_independence",
        (SectionRequirement("Safety rules", ("only when work is independent",)),),
        carried=(
            CarriedEntry(
                "safety_rules",
                "[capability:coordinated_scope] Use coordination lanes only when work is independent; "
                "if two lanes are not independent, collapse them under one owner or re-plan before dispatch.",
            ),
        ),
        notes=(
            "Distinct from the target's pre-existing file/ownership disjointness rules: this is the "
            "work-independence precondition for opening coordination lanes at all."
        ),
    ),
    _obligation(
        "team.collision_prevention",
        "safety_rules",
        "Keep shared-file edits under one owner.",
        "unique",
        "missing_collision_prevention",
        (SectionRequirement("Safety rules", ("shared-file edits under one owner",)),),
        carried=(
            CarriedEntry(
                "safety_rules",
                "[capability:coordinated_scope] Keep shared-file edits under one owner; if integration "
                "reveals a shared-file conflict, stop lane fan-out and reassign ownership before continuing.",
            ),
        ),
    ),
    _obligation(
        "team.not_observed_labeling",
        "safety_rules",
        "Record unobserved delegation as not_observed.",
        "shared_with",
        "missing_not_observed_labeling",
        (SectionRequirement("Safety rules", ("unobserved delegation as not_observed",)),),
        shared_with=("ultraprocess",),
        carried=(
            CarriedEntry(
                "safety_rules",
                "[capability:coordinated_scope] Record unobserved delegation as not_observed; a delegation "
                "record exists only when separate participants are observed.",
            ),
        ),
        notes=(
            "Also carries team.artifact_expectations -- 'delegation record only when separate participants "
            "are observed'. ultraprocess's evidence duty is carried by its own delivery_boundary line, so "
            "removal fires exactly this code."
        ),
    ),
    _obligation(
        "team.failure_propagation",
        "recovery_notes",
        "If a worker has no ACK or result, mark that lane not_observed or blocked rather than infer progress.",
        "unique",
        "missing_failure_propagation",
        (SectionRequirement("Recovery Notes", ("rather than infer progress",)),),
        carried=(
            CarriedEntry(
                "recovery_notes",
                "[capability:coordinated_scope] If a coordinated worker has no ACK or result, mark that "
                "lane not_observed or blocked rather than infer progress.",
            ),
        ),
        notes=(
            "Near-overlap decision: the target's pre-existing recovery line exposes retry/reassignment; "
            "team's duty adds the anti-inference rule ('rather than infer progress'), which the pre-fold "
            "contract does not carry, so this stays counted per the plan's §8.3 row."
        ),
    ),
    _obligation(
        "team.integrated_status",
        "final_checklist",
        "The integrated status names which lanes are observed, blocked, or still prepared_not_observed.",
        "unique",
        "missing_integrated_status",
        (SectionRequirement("Completion Checklist", ("integrated status names which",)),),
        carried=(
            CarriedEntry(
                "final_checklist",
                "[capability:coordinated_scope] The integrated status names which coordination lanes are "
                "observed, blocked, or still prepared_not_observed.",
            ),
        ),
    ),
    _obligation(
        "team.coordinator_role",
        "quality_bar",
        "Keep Hermes as coordinator and status narrator while coding lanes become runtime handoffs with explicit ownership.",
        "unique",
        "missing_coordinator_role",
        (SectionRequirement("Quality bar", ("coordinator and status narrator",)),),
        carried=(
            CarriedEntry(
                "quality_bar",
                "[capability:coordinated_scope] Keep Hermes as coordinator and status narrator for lane "
                "framing and status while coding lanes become runtime handoffs with explicit ownership.",
            ),
        ),
        notes="Also carries team.handoff_policy -- 'Use Hermes for lane framing and status; ...'.",
    ),
    _obligation(
        "team.lane_ownership",
        "final_checklist",
        "Each lane has an owner, disjoint scope, expected output, and verification target.",
        "pre_existing_in_target",
        "",
        (
            SectionRequirement("Quality bar", ("disjoint lane ownership",)),
            SectionRequirement("Completion Checklist", ("disjoint by file, invariant, or responsibility",)),
        ),
        notes="Reclassified from unique by the satisfaction tie-break (plan rev 4).",
    ),
    _obligation(
        "team.worker_evidence_separation",
        "final_checklist",
        "Worker ACK, dispatch, result, integration, and verification evidence are separated when wrappers record them.",
        "pre_existing_in_target",
        "",
        (
            SectionRequirement("Completion Checklist", ("Worker ACK, dispatch, result",)),
            SectionRequirement("Completion Checklist", ("Integration verification ran after lane results",)),
        ),
        notes=(
            "Noted near-match (plan Critic m3): the target's list names review/CI/merge where team's names "
            "integration/verification. PR D decision: integration evidence needs no separate counted "
            "obligation because the target's pre-existing 'Integration verification ran after lane results' "
            "line carries the divergent tail; this pin requires both lines."
        ),
    ),
    _obligation(
        "team.coding_harness_lanes",
        "final_checklist",
        "Hermes-owned coding teams use `hermes_coding_harness/v1` so builder, verifier, reviewer, docs, and PR lanes stay distinct even in solo mode.",
        "pre_existing_in_target",
        "",
        (SectionRequirement("Completion Checklist", ("hermes_coding_harness/v1",)),),
    ),
    _obligation(
        "team.engine_entry_confirmation",
        "quality_bar",
        "ENGINE_ENTRY_CONFIRMATION_RULE",
        "pre_existing_in_target",
        "",
        (SectionRequirement("Quality bar", ("explicit go-ahead",)),),
    ),
    _obligation(
        "team.ultrawork_boundary",
        "do_not_use_when",
        "An accepted implementation plan with disjoint files, criteria, and commands is ready for parallel delivery; use `ultrawork`.",
        "dissolves_on_fold",
        "",
        (SectionRequirement("Do Not Use When", ()),),
        notes="Named target `ultrawork` is the fold target; the boundary points at itself after the fold.",
    ),
)

_ULTRAPROCESS_OBLIGATIONS = (
    _obligation(
        "ultraprocess.single_cycle_stop",
        "quality_bar",
        "Complete exactly one plan-to-PR delivery cycle, then stop with status, evidence gaps, or a next recommended workflow.",
        "unique",
        "missing_single_cycle_stop",
        (SectionRequirement("Quality bar", ("exactly one plan-to-PR delivery cycle",)),),
        carried=(
            CarriedEntry(
                "quality_bar",
                "[capability:delivery_boundary] Complete exactly one plan-to-PR delivery cycle, then stop "
                "with status, evidence gaps, or a next recommended workflow.",
            ),
        ),
    ),
    _obligation(
        "ultraprocess.loop_boundary",
        "safety_rules",
        "Do not continue into a repeated feedback loop; recommend `loop` when the user wants ongoing cycles.",
        "unique",
        "missing_loop_boundary",
        (SectionRequirement("Safety rules", ("repeated feedback loop", "recommend `loop`")),),
        carried=(
            CarriedEntry(
                "safety_rules",
                "[capability:delivery_boundary] Do not continue into a repeated feedback loop; recommend "
                "`loop` when the user wants ongoing cycles.",
            ),
        ),
    ),
    _obligation(
        "ultraprocess.research_first",
        "quality_bar",
        "Start with codebase/source research and a ralplan-style decision record before implementation handoff.",
        "unique",
        "missing_research_first",
        (SectionRequirement("Quality bar", ("codebase/source research", "before implementation handoff")),),
        carried=(
            CarriedEntry(
                "quality_bar",
                "[capability:delivery_boundary] Start a delivery cycle with codebase/source research and a "
                "ralplan-style decision record before implementation handoff.",
            ),
        ),
    ),
    _obligation(
        "ultraprocess.plan_gate",
        "safety_rules",
        "Do not skip planning when the request is broad, risky, or user-visible.",
        "unique",
        "missing_plan_gate",
        (SectionRequirement("Safety rules", ("Do not skip planning",)),),
        carried=(
            CarriedEntry(
                "safety_rules",
                "[capability:delivery_boundary] Do not skip planning when the delivery request is broad, "
                "risky, or user-visible; a ralplan-style or reviewed plan names acceptance criteria, risks, "
                "and verification commands.",
            ),
        ),
    ),
    _obligation(
        "ultraprocess.review_gate",
        "quality_bar",
        "Run code-review as a gate after implementation evidence exists; review preparation alone is not review evidence.",
        "unique",
        "missing_review_gate",
        (SectionRequirement("Quality bar", ("code-review as a gate",)),),
        carried=(
            CarriedEntry(
                "quality_bar",
                "[capability:delivery_boundary] Run code-review as a gate after implementation evidence "
                "exists; review preparation alone is not review evidence.",
            ),
        ),
    ),
    _obligation(
        "ultraprocess.docs_sync",
        "safety_rules",
        "Run docs sync only when behavior, setup, commands, or public claims changed.",
        "unique",
        "missing_docs_sync",
        (SectionRequirement("Safety rules", ("docs sync only when",)),),
        carried=(
            CarriedEntry(
                "safety_rules",
                "[capability:delivery_boundary] Run docs sync only when behavior, setup, commands, "
                "examples, or public claims changed.",
            ),
        ),
    ),
    _obligation(
        "ultraprocess.evidence_state_separation",
        "quality_bar",
        "End with a PR-ready or PR-observed report that separates prepared, executed, reviewed, verified, CI, and PR evidence.",
        "shared_with",
        "evidence_state_collapse",
        (
            SectionRequirement(
                "Quality bar",
                ("separates prepared, executed, reviewed, verified, CI, and PR evidence",),
            ),
        ),
        shared_with=("team",),
        carried=(
            CarriedEntry(
                "quality_bar",
                "[capability:delivery_boundary] End a delivery cycle with a PR-ready or PR-observed report "
                "that separates prepared, executed, reviewed, verified, CI, and PR evidence.",
            ),
        ),
        notes=(
            "team's worker-evidence separation duty is satisfied by the target's pre-existing checklist "
            "line, so removal of this carrier fires exactly this code."
        ),
    ),
    _obligation(
        "ultraprocess.owner_neutrality",
        "handoff_policy",
        "...convert implementation into a selected executor/runtime handoff such as Codex, Claude Code, OMX/OMO/OMC, another coding agent, or explicit Hermes coding runtime only when the user accepts that owner.",
        "unique",
        "owner_neutrality_lost",
        (SectionRequirement("Handoff policy", ("only when the user accepts that owner",)),),
        carried=(
            CarriedEntry(
                "handoff_policy",
                "[capability:delivery_boundary] Convert implementation into an external executor/runtime "
                "handoff such as Codex, Claude Code, OMX/OMO/OMC, or another coding agent only when the user "
                "accepts that owner; no external CLI is the default owner, and external handoff is a separate "
                "opt-in path, never the default recommendation.",
            ),
        ),
        notes=(
            "Tie-break checked first per plan §8.4: the pre-fold handoff policy speaks about selected "
            "runtime handoffs but never carries the user-accepted-owner clause, so this stays counted."
        ),
    ),
    _obligation(
        "ultraprocess.delivery_to_durable_handoff",
        "quality_bar",
        "For implementation, hand off to ultragoal or the selected executor/runtime path with acceptance criteria and verification commands attached...",
        "unique",
        "missing_delivery_to_durable_handoff",
        (
            SectionRequirement("Quality bar", ("hand off to the `durable_checkpoint` capability",)),
            SectionRequirement(
                "Expected outputs", ("`durable_checkpoint` or selected executor/runtime handoff",)
            ),
        ),
        carried=(
            CarriedEntry(
                "quality_bar",
                "[capability:delivery_boundary] For implementation, default to Hermes-native delegation with "
                "a per-lane `omh_delegate_route` mixture route and acceptance criteria and verification "
                "commands attached; hand off to the `durable_checkpoint` capability for work that must "
                "survive sessions, and prepare a selected external executor/runtime path only on the user's "
                "explicit owner acceptance.",
            ),
            CarriedEntry(
                "expected_outputs",
                "[capability:delivery_boundary] `durable_checkpoint` or selected executor/runtime handoff",
            ),
        ),
        notes=(
            "Reclassified unique in plan rev 4: the ultragoal handoff survives as the internal "
            "delivery_boundary -> durable_checkpoint reference, asserted in both rendered directions."
        ),
    ),
    _obligation(
        "ultraprocess.core_network_boundary",
        "safety_rules",
        "Keep web research source-backed and permission-aware; do not run hidden network or LLM calls from OMH core.",
        "unique",
        "missing_core_network_boundary",
        (SectionRequirement("Safety rules", ("hidden network or LLM calls",)),),
        carried=(
            CarriedEntry(
                "safety_rules",
                "[capability:delivery_boundary] Keep web research source-backed and permission-aware; do "
                "not run hidden network or LLM calls from OMH core.",
            ),
        ),
    ),
    _obligation(
        "ultraprocess.loop_routing_boundary",
        "do_not_use_when",
        "The user wants an open-ended feedback loop or long-horizon campaign; use `loop` instead.",
        "unique",
        "missing_loop_routing_boundary",
        (
            SectionRequirement(
                "Do Not Use When", ("open-ended feedback loop or long-horizon campaign", "use `loop`")
            ),
        ),
        carried=(
            CarriedEntry(
                "do_not_use_when",
                "[capability:delivery_boundary] The user wants an open-ended feedback loop or long-horizon "
                "campaign; use `loop` instead.",
            ),
        ),
        notes=(
            "`loop` is retained, so the admission rule makes this boundary ineligible for "
            "dissolves_on_fold; it is the goal-mutability axis's load-bearing distinction."
        ),
    ),
    _obligation(
        "ultraprocess.engine_entry_confirmation",
        "quality_bar",
        "ENGINE_ENTRY_CONFIRMATION_RULE",
        "pre_existing_in_target",
        "",
        (SectionRequirement("Quality bar", ("explicit go-ahead",)),),
    ),
    _obligation(
        "ultraprocess.coding_harness_staging",
        "final_checklist",
        "If the implementation owner is Hermes, `hermes_coding_harness/v1` names the current stage, lane owner, next action, and missing evidence.",
        "pre_existing_in_target",
        "",
        (SectionRequirement("Completion Checklist", ("hermes_coding_harness/v1",)),),
        notes=(
            "Satisfied by the target's harness lane-separation line; the stage-naming tail is harness "
            "behavior the retained `hermes_coding_harness/v1` contract already owns."
        ),
    ),
)

_RALPH_OBLIGATIONS = (
    _obligation(
        "ralph.concrete_entry_gate",
        "quality_bar",
        "Do not enter a finish-until-done loop until scope, acceptance criteria, and verification commands are concrete.",
        "unique",
        "missing_concrete_entry_gate",
        (
            SectionRequirement(
                "Quality bar",
                ("finish-until-done loop until scope, acceptance criteria, and verification commands are concrete",),
            ),
        ),
        carried=(
            CarriedEntry(
                "quality_bar",
                "[capability:single_owner_persistence] Do not enter a finish-until-done loop until scope, "
                "acceptance criteria, and verification commands are concrete.",
            ),
        ),
        notes="Also carries ralph.required_inputs -- 'concrete scope', 'acceptance criteria', 'verification commands'.",
    ),
    _obligation(
        "ralph.tracked_runtime_evidence",
        "quality_bar",
        "For coding edits, prepare and track selected runtime evidence instead of implying unobserved work happened.",
        "unique",
        "missing_tracked_runtime_evidence",
        (SectionRequirement("Quality bar", ("prepare and track the selected runtime path",)),),
        carried=(
            CarriedEntry(
                "quality_bar",
                "[capability:single_owner_persistence] For single-owner coding edits, prepare and track the "
                "selected runtime path instead of implying unobserved work happened or hiding execution "
                "inside chat narration.",
            ),
        ),
        notes="Also carries ralph.handoff_policy -- '...instead of hiding execution inside chat narration.'",
    ),
    _obligation(
        "ralph.observed_completion_gate",
        "quality_bar",
        "Report completion only from observed execution and verification evidence.",
        "unique",
        "missing_observed_completion_gate",
        (SectionRequirement("Quality bar", ("only from observed execution and verification evidence",)),),
        carried=(
            CarriedEntry(
                "quality_bar",
                "[capability:single_owner_persistence] Report single-owner completion only from observed "
                "execution and verification evidence, with remaining risks named.",
            ),
        ),
        notes="Also carries ralph.expected_outputs -- 'completed work summary', 'verification evidence', 'remaining risks'.",
    ),
    _obligation(
        "ralph.persistence_to_durable_boundary",
        "do_not_use_when",
        "Progress must survive sessions as a ledger with multiple checkpoints and a final gate; use `ultragoal`.",
        "unique",
        "missing_persistence_to_durable_boundary",
        (SectionRequirement("Do Not Use When", ("survive sessions as a ledger", "`durable_checkpoint`")),),
        carried=(
            CarriedEntry(
                "do_not_use_when",
                "[capability:single_owner_persistence] Progress must survive sessions as a ledger with "
                "multiple checkpoints and a final gate; use the `durable_checkpoint` capability.",
            ),
        ),
        notes=(
            "`ultragoal` is folding (admissible for dissolves) but the boundary still discriminates two "
            "surviving capabilities, so it is carried as the internal single_owner_persistence -> "
            "durable_checkpoint reference, mirroring the ultraprocess -> ultragoal precedent."
        ),
    ),
    _obligation(
        "ralph.direct_handling_boundary",
        "do_not_use_when",
        "The request is a settings-only change, one bounded edit that is explicitly low-risk and has a direct owner and verification path, or a direct answer/diagnosis; handle it directly instead of opening a finish-until-done loop.",
        "shared_with",
        "missing_direct_handling_boundary",
        (SectionRequirement("Do Not Use When", ("a finish-until-done loop, or a goal ledger",)),),
        shared_with=("ultragoal",),
        carried=(
            CarriedEntry(
                "do_not_use_when",
                "[capability:single_owner_persistence] The request is a settings-only change, one bounded "
                "edit that is explicitly low-risk and has a direct owner and verification path, or a direct "
                "answer/diagnosis; use one direct owner instead of opening parallel delivery lanes, a "
                "finish-until-done loop, or a goal ledger.",
            ),
        ),
        notes=(
            "One carrier covers ralph's finish-until-done denial and ultragoal's settings-only/single-turn "
            "goal-ledger denial; counted once, attributed to both. The target's pre-existing settings-only "
            "line denies only parallel delivery lanes, so this stays counted."
        ),
    ),
    _obligation(
        "ralph.persistence_run_record",
        "artifact_expectations",
        "goal-execution run record",
        "unique",
        "missing_persistence_run_record",
        (SectionRequirement("Artifact expectations", ("goal-execution run record",)),),
        carried=(
            CarriedEntry(
                "artifact_expectations",
                "[capability:single_owner_persistence] goal-execution run record with checkpoint or final "
                "evidence when available",
            ),
        ),
        notes="Also carries ralph.artifact_expectations -- 'checkpoint or final evidence when available'.",
    ),
    _obligation(
        "ralph.engine_entry_confirmation",
        "quality_bar",
        "ENGINE_ENTRY_CONFIRMATION_RULE",
        "pre_existing_in_target",
        "",
        (SectionRequirement("Quality bar", ("explicit go-ahead",)),),
    ),
)

_ULTRAGOAL_OBLIGATIONS = (
    _obligation(
        "ultragoal.durable_ledger",
        "quality_bar",
        "Keep goal state durable, inspectable, and separate from chat narration.",
        "unique",
        "missing_durable_ledger",
        (SectionRequirement("Quality bar", ("durable, inspectable, and separate from chat narration",)),),
        carried=(
            CarriedEntry(
                "quality_bar",
                "[capability:durable_checkpoint] Keep goal state durable, inspectable, and separate from "
                "chat narration in the metadata-only .omh/goals goal_ledger/v1.",
            ),
        ),
        notes="Also carries ultragoal.handoff_policy and artifact_expectations ledger duties.",
    ),
    _obligation(
        "ultragoal.checkpoint_discipline",
        "quality_bar",
        "Checkpoint every success, blocker, and final quality gate with fresh evidence.",
        "unique",
        "missing_checkpoint_discipline",
        (SectionRequirement("Quality bar", ("Checkpoint every success, blocker, and final quality gate",)),),
        carried=(
            CarriedEntry(
                "quality_bar",
                "[capability:durable_checkpoint] Checkpoint every success, blocker, and final quality gate "
                "with fresh evidence.",
            ),
        ),
    ),
    _obligation(
        "ultragoal.completion_gate",
        "quality_bar",
        "Reject completion with a summary-only goal_completion_gate/v1 result until required criteria, blockers, and explicitly linked runtime runs are satisfied.",
        "unique",
        "missing_completion_gate",
        (SectionRequirement("Quality bar", ("summary-only goal_completion_gate/v1",)),),
        carried=(
            CarriedEntry(
                "quality_bar",
                "[capability:durable_checkpoint] Reject completion with a summary-only "
                "goal_completion_gate/v1 result until required criteria, blockers, and explicitly linked "
                "runtime runs are satisfied.",
            ),
        ),
    ),
    _obligation(
        "ultragoal.next_action_status",
        "quality_bar",
        "Tell the user the next action through goal_status_card/v1 or goal_continuation/v1 instead of ending with vague follow-up copy.",
        "unique",
        "missing_next_action_status",
        (
            SectionRequirement(
                "Completion Checklist",
                ("goal_status_card/v1 or goal_continuation/v1", "complete, blocked, or continue"),
            ),
        ),
        carried=(
            CarriedEntry(
                "final_checklist",
                "[capability:durable_checkpoint] The goal_status_card/v1 or goal_continuation/v1 names the "
                "next action and the final status says complete, blocked, or continue with the exact "
                "remaining checkpoint.",
            ),
        ),
        notes=(
            "Also carries ultragoal.final_checklist -- 'The final user-facing status says complete, "
            "blocked, or continue with the exact remaining checkpoint.'"
        ),
    ),
    _obligation(
        "ultragoal.linked_milestone_evidence",
        "final_checklist",
        "All explicitly linked coding milestones have matching observed runtime evidence or are still named as gaps.",
        "unique",
        "missing_linked_milestone_evidence",
        (SectionRequirement("Completion Checklist", ("explicitly linked coding milestones",)),),
        carried=(
            CarriedEntry(
                "final_checklist",
                "[capability:durable_checkpoint] All explicitly linked coding milestones have matching "
                "observed runtime evidence or stay prepared_not_observed and named as gaps without closing "
                "the goal.",
            ),
        ),
        notes=(
            "Also carries ultragoal.recovery_notes -- 'If linked runtime evidence is missing, keep coding "
            "milestones prepared_not_observed and do not close the goal.'"
        ),
    ),
    _obligation(
        "ultragoal.background_milestone_reporting",
        "final_checklist",
        "Long-running or background executor milestones report observed handles, current state, changed-file summaries, missing checks, and prepared-vs-observed boundaries while work is running.",
        "unique",
        "missing_background_milestone_reporting",
        (
            SectionRequirement(
                "Completion Checklist", ("observed handles, current state, changed-file summaries",)
            ),
        ),
        carried=(
            CarriedEntry(
                "final_checklist",
                "[capability:durable_checkpoint] Long-running or background executor milestones report "
                "observed handles, current state, changed-file summaries, missing checks, and "
                "prepared-vs-observed boundaries while work is running.",
            ),
        ),
    ),
    _obligation(
        "ultragoal.merge_claim_verification",
        "final_checklist",
        "Branch, PR, CI, review, and merge claims are verified against local HEAD, remote branch SHA, PR head SHA, and merge commit before saying a fix landed.",
        "unique",
        "missing_merge_claim_verification",
        (
            SectionRequirement(
                "Completion Checklist",
                ("local HEAD, remote branch SHA, PR head SHA, and merge commit",),
            ),
        ),
        carried=(
            CarriedEntry(
                "final_checklist",
                "[capability:durable_checkpoint] Branch, PR, CI, review, and merge claims are verified "
                "against local HEAD, remote branch SHA, PR head SHA, and merge commit before saying a fix "
                "landed.",
            ),
        ),
    ),
    _obligation(
        "ultragoal.checkpoint_resume",
        "recovery_notes",
        "If the goal ledger is stale or missing, inspect .omh/goals and ask which checkpoint to resume before continuing.",
        "unique",
        "missing_checkpoint_resume",
        (SectionRequirement("Recovery Notes", (".omh/goals", "which checkpoint to resume")),),
        carried=(
            CarriedEntry(
                "recovery_notes",
                "[capability:durable_checkpoint] If the goal ledger is stale or missing, inspect .omh/goals "
                "and ask which checkpoint to resume before continuing.",
            ),
        ),
    ),
    _obligation(
        "ultragoal.blocker_checkpoint",
        "recovery_notes",
        "If a blocker checkpoint exists, keep the goal open and record the blocker plus the smallest unblock action.",
        "unique",
        "missing_blocker_checkpoint",
        (SectionRequirement("Recovery Notes", ("keep the goal open", "smallest unblock action")),),
        carried=(
            CarriedEntry(
                "recovery_notes",
                "[capability:durable_checkpoint] If a blocker checkpoint exists, keep the goal open and "
                "record the blocker plus the smallest unblock action.",
            ),
        ),
    ),
    _obligation(
        "ultragoal.goal_loop_boundary",
        "do_not_use_when",
        "The next work must be discovered or reframed repeatedly through research and feedback cycles; use `loop`.",
        "unique",
        "missing_goal_loop_boundary",
        (SectionRequirement("Do Not Use When", ("discovered or reframed repeatedly",)),),
        carried=(
            CarriedEntry(
                "do_not_use_when",
                "[capability:durable_checkpoint] The next work must be discovered or reframed repeatedly "
                "through research and feedback cycles; use `loop`.",
            ),
        ),
        notes="`loop` is retained, so the admission rule keeps this boundary counted.",
    ),
    _obligation(
        "ultragoal.durable_to_persistence_boundary",
        "do_not_use_when",
        "One concrete, already-scoped task only needs one owner to finish and verify; use `ralph`.",
        "unique",
        "missing_durable_to_persistence_boundary",
        (SectionRequirement("Do Not Use When", ("one owner to finish and verify", "`single_owner_persistence`")),),
        carried=(
            CarriedEntry(
                "do_not_use_when",
                "[capability:durable_checkpoint] One concrete, already-scoped task only needs one owner to "
                "finish and verify; use the `single_owner_persistence` capability.",
            ),
        ),
        notes="Reciprocal of ralph.persistence_to_durable_boundary; survives as an internal reference.",
    ),
    _obligation(
        "ultragoal.inspectable_goal_entry",
        "do_not_use_when",
        "Acceptance criteria, current checkpoint, and final gate expectations are too vague to make a goal inspectable.",
        "unique",
        "missing_inspectable_goal_entry",
        (SectionRequirement("Do Not Use When", ("too vague to make a goal inspectable",)),),
        carried=(
            CarriedEntry(
                "do_not_use_when",
                "[capability:durable_checkpoint] Acceptance criteria, current checkpoint, and final gate "
                "expectations are too vague to make a goal inspectable.",
            ),
        ),
    ),
    _obligation(
        "ultragoal.engine_entry_confirmation",
        "quality_bar",
        "ENGINE_ENTRY_CONFIRMATION_RULE",
        "pre_existing_in_target",
        "",
        (SectionRequirement("Quality bar", ("explicit go-ahead",)),),
    ),
    _obligation(
        "ultragoal.hidden_execution_boundary",
        "do_not_use_when",
        "The user expects hidden Hermes code execution rather than explicit executor handoff and observed verification evidence.",
        "pre_existing_in_target",
        "",
        (SectionRequirement("Do Not Use When", ("secretly execute",)),),
        notes="Satisfied by the target's 'secretly execute coding lanes' boundary.",
    ),
    _obligation(
        "ultragoal.coding_harness_lanes",
        "final_checklist",
        "When Hermes is the coding owner, use `hermes_coding_harness/v1` to separate builder, verifier, reviewer, docs, and PR lanes.",
        "pre_existing_in_target",
        "",
        (SectionRequirement("Completion Checklist", ("hermes_coding_harness/v1",)),),
    ),
)

# The teardown rule is a `new_requirement` on coordinated_scope (plan §4.2):
# `team` has no teardown obligation, so it is gated by its own presence test in
# tests/test_ulw_equivalence.py, never scored as proven equivalence.
COORDINATED_SCOPE_TEARDOWN_TEXT = (
    "[capability:coordinated_scope] Coordination teardown is explicit: released lanes are named and "
    "closed instead of lingering as implicit owners."
)

# Frozen source baselines, re-pinned at retirement (#954 stage 5, window=0).
# The PR D captures pinned the pre-fold routing and harness legs; stage 5
# deliberately moved both -- the representative cues now resolve the
# `ulw-work` alias and the retired contracts left the primary-harness map --
# so the digests were recomputed once, in the same commit as the change that
# moved them, and disclosed in the PR body. The definition-field leg is
# unchanged; a future mismatch still means someone edited a retired contract.
_SOURCE_BASELINE_DIGESTS = {
    "team": "50918dc931ca52c9ca1fda1a9088e0e4f1997faa45eab6bc4a0d4645fd69b835",
    "ultraprocess": "0168d5886a4fa18c0a4b86b5007c80b4e229f5ce0e3a92fbbe40ae411f9eba5b",
    "ralph": "99a7d3146874ebc3a4ed31c3dcebf2466f16f952a606beae7fbba9b6d75f2bf3",
    "ultragoal": "5f22c848d61e0c7ffa2a6230e8eaba8803a28f852431bc8b7be8a8b50a184db9",
}

CONTRACT_EQUIVALENCE_CASES = (
    ContractEquivalenceCase(
        contract_id="team",
        target_capability="coordinated_scope",
        baseline_digest=_SOURCE_BASELINE_DIGESTS["team"],
        obligations=_TEAM_OBLIGATIONS,
    ),
    ContractEquivalenceCase(
        contract_id="ultraprocess",
        target_capability="delivery_boundary",
        baseline_digest=_SOURCE_BASELINE_DIGESTS["ultraprocess"],
        obligations=_ULTRAPROCESS_OBLIGATIONS,
    ),
    ContractEquivalenceCase(
        contract_id="ralph",
        target_capability="single_owner_persistence",
        baseline_digest=_SOURCE_BASELINE_DIGESTS["ralph"],
        obligations=_RALPH_OBLIGATIONS,
    ),
    ContractEquivalenceCase(
        contract_id="ultragoal",
        target_capability="durable_checkpoint",
        baseline_digest=_SOURCE_BASELINE_DIGESTS["ultragoal"],
        obligations=_ULTRAGOAL_OBLIGATIONS,
    ),
)
