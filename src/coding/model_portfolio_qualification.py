"""Pure, evidence-bounded qualification of a complete caller-supplied inventory.

This report never discovers models, calls providers, edits chains, or promotes a
model merely because a chain names it. Decisions are reviewed metadata, not
measurements. Inventory identity parsing is shared with the contract audit.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from typing import Final, Iterable, Mapping

from .model_contract_coverage import (
    MODEL_CONTRACT_COVERAGE_CLAIM_BOUNDARY,
    _SOURCE_LINEAGE_KEY,
    _digest,
    _inventory_model_refs,
    _inventory_record,
    _model_ref,
    _normalized_refs,
    _price_dimension,
    _validate_inventory_shape,
)
from .model_contracts import (
    EXACT_CONTRACT_POINTER_ALIASES,
    MODEL_CONTRACTS,
    contract_model_id,
    model_contract,
    model_contract_projection,
)
from .model_recommendations import SHIPPED_MODEL_RECOMMENDATIONS
from .model_routing import model_family
from .unit_prompt_protocol import (
    HIGH_EFFORT_CALIBRATIONS,
    MAIN_AGENT_COMPOSITION_CALIBRATIONS,
    MODEL_COMPOSITION_CALIBRATIONS,
    MODEL_HIGH_EFFORT_CALIBRATIONS,
)

MODEL_PORTFOLIO_QUALIFICATION_SCHEMA_VERSION: Final = "model_portfolio_qualification/v1"
PORTFOLIO_DISPOSITIONS: Final = (
    "recommended",
    "eligible_not_selected",
    "excluded_quality_dominated",
    "excluded_efficiency_dominated",
    "excluded_tool_unreliable",
    "excluded_runtime_incompatible",
    "excluded_superseded",
    "unmeasured",
)
_SECTIONS: Final = ("categories", "role_suggestions", "domain_affinities", "last_resort")

# Reviewed decisions, NOT a supported-model allowlist. Anything absent from
# these tables still gets a row, but never gets recommendation standing.
# The inventory establishes presence; the calibration tables establish the
# missing pair. Neither establishes poor quality or runtime incompatibility.
# These explicit holds exclude promotion, while keeping the honest unmeasured
# disposition until research and separately approved measurement close them.
QUALIFICATION_HOLDS: Final[dict[str, dict[str, object]]] = {
    model: {
        "disposition": "unmeasured",
        "reason": "Qualification held: no dedicated calibration pair or role-evaluation evidence; generic guidance is not optimization.",
        "dimension": "calibration_evidence",
        "evidence_state": "unmeasured",
        "evidence_pointers": [
            "https://github.com/rlaope/oh-my-hermes/issues/1515",
            "src/coding/unit_prompt_protocol.py:HIGH_EFFORT_CALIBRATIONS",
            "src/coding/unit_prompt_protocol.py:MAIN_AGENT_COMPOSITION_CALIBRATIONS",
            "MODEL_OPTI.md#coverage-matrix-and-known-gaps",
        ],
        "decision_date": "2026-09-13",
        "scope": "qualification_hold",
    }
    for model in (
        "minimax-m3", "mimo-v2.5-pro", "hy4-preview", "hy3",
        "step-3.7-flash", "nemotron-3-super-120b-a12b", "fugu-ultra",
    )
}
# Existing owner-approved editorial placements, reviewed 2026-09-13 against
# model_recommendations.py. This independent registry is deliberately NOT
# computed from the catalog: adding a candidate or a new role must fail the
# qualification guard until its evidence decision lands in the same change.
# No new measured advantage is claimed by grandfathering these placements.
# Re-reviewed 2026-10-13 against the owner's table of that date: every slot
# below is that decision, editorial except the `unspecified-high` GPT head,
# which rests on the 2026-09-05 live-model-tools measurement of its
# predecessor (gpt-5.6-sol); GPT-6.1 Sol itself is unmeasured there.
# The six routing-recipe categories (google-search, x-search, review, swarm,
# forensics, synthesize) were added on 2026-10-28 from the owner's published
# recipe; every slot they add is editorial and unmeasured.
# ultrabrain gained Claude Fable 5.1 (head) and Claude Opus 5.5 (third) on
# 2026-11-09 (owner decision), editorial and unmeasured.
RECOMMENDATION_DECISIONS: Final[dict[str, tuple[str, ...]]] = {
    "claude-fable-5-1": (
        "categories:architect", "categories:artistry", "categories:capable",
        "categories:ultrabrain", "categories:visual-engineering", "role_suggestions:main",
    ),
    "claude-haiku-5-5": ("categories:quick", "categories:simple-work"),
    "claude-opus-5-5": (
        "categories:architect", "categories:artistry", "categories:capable", "categories:deep",
        "categories:deep-work", "categories:forensics", "categories:google-search",
        "categories:review", "categories:synthesize", "categories:ultrabrain", "categories:unspecified-high",
        "categories:visual-engineering", "categories:writing", "last_resort:any", "role_suggestions:main",
    ),
    "claude-sonnet-5-5": ("categories:unspecified-low", "categories:writing"),
    "deepseek-flash": ("categories:simple-work", "categories:swarm", "categories:unspecified-low"),
    "gemini-4-argon": (
        "categories:artistry", "categories:google-search", "categories:synthesize",
        "categories:visual-engineering", "categories:writing", "categories:x-search",
        "domain_affinities:x_platform_data",
    ),
    "glm-5.3": ("categories:unspecified-low",),
    "glm-5.3-flash": ("categories:quick", "categories:swarm"),
    "gpt-6-astra": (
        "categories:architect", "categories:forensics", "categories:ultrabrain", "role_suggestions:main",
    ),
    "gpt-6-luna": ("categories:quick", "categories:simple-work", "categories:swarm"),
    "gpt-6.1-sol": (
        "categories:capable", "categories:deep", "categories:deep-work", "categories:google-search",
        "categories:review", "categories:synthesize", "categories:unspecified-high",
        "categories:unspecified-low", "last_resort:any", "role_suggestions:main",
    ),
    # Grok 4.7 heads x-search (owner recipe, 2026-10-28), editorial and
    # unmeasured; the x_platform_data affinity stays on Grok Build 0.1.
    "grok-4.7": ("categories:x-search",),
    "grok-build-0.1": ("domain_affinities:x_platform_data",),
    "kimi-k3.1-pro": (
        "categories:architect", "categories:artistry", "categories:capable", "categories:deep",
        "categories:forensics", "categories:quick", "categories:review", "categories:unspecified-high",
        "categories:visual-engineering", "categories:writing", "categories:x-search",
        "domain_affinities:x_platform_data", "role_suggestions:main",
    ),
}
# Each row carries its own decision date: retirements land one onboarding at
# a time, so a shared date would misdate every row after the first round.
RETIREMENT_DECISIONS: Final[dict[str, dict[str, object]]] = {
    model: {
        "disposition": "excluded_superseded",
        "successor": successor,
        "reason": f"Owner retired this generation from {scope}; successor is {successor}.",
        "scope": scope,
        "decision_date": decision_date,
        "evidence_state": "editorial_not_measured",
        "evidence_pointers": ["docs/MODEL-ONBOARDING.md#4-place-routing", "src/coding/model_recommendations.py"],
    }
    for model, successor, scope, decision_date in (
        ("claude-fable-5", "claude-fable-5-1", "all_shipped_chains", "2026-09-11"),
        ("glm-5.2", "glm-5.3", "all_shipped_chains", "2026-09-11"),
        ("glm-5.2-ultrafast", "glm-5.3-flash", "all_shipped_chains", "2026-09-11"),
        ("deepseek-v3.2", "deepseek-v4.1-flash", "all_shipped_chains", "2026-09-11"),
        ("claude-opus-5", "claude-opus-5-5", "all_shipped_chains", "2026-09-23"),
        ("gpt-5.6-luna", "gpt-6-luna", "all_shipped_chains", "2026-09-23"),
        # The dict is keyed by model id, so GPT-5.6 Sol's row is rewritten,
        # not appended: its 2026-09-11 frontier-slot retirement (successor
        # gpt-6-astra) is widened here to every shipped chain. That history
        # stays in docs/MODEL-ONBOARDING.md.
        ("gpt-5.6-sol", "gpt-6-sol", "all_shipped_chains", "2026-09-23"),
        ("gpt-5.6-terra", "gpt-6-sol", "all_shipped_chains", "2026-09-23"),
        # xAI retired Grok Code Fast on 2026-05-15 and lists its ids as
        # aliases of Grok Build 0.1.
        ("grok-code-fast", "grok-build-0.1", "all_shipped_chains", "2026-10-01"),
        ("gpt-6-sol", "gpt-6.1-sol", "all_shipped_chains", "2026-10-01"),
        ("claude-haiku-4-5", "claude-haiku-5-5", "all_shipped_chains", "2026-10-13"),
        ("kimi-k3", "kimi-k3.1-pro", "all_shipped_chains", "2026-10-24"),
        # Google made Gemini 4 Argon generally available on 2026-10-13.
        ("gemini-3.1-pro", "gemini-4-argon", "all_shipped_chains", "2026-10-28"),
    )
} | {
    # Qwen3-Coder (2025) left its only slot on 2026-10-13 and no Qwen-line
    # generation replaced it, so the row is written out rather than generated:
    # an empty successor, and a reason that names the model now holding the
    # slot instead of calling it a successor generation.
    "qwen3-coder": {
        "disposition": "excluded_superseded",
        "successor": "",
        "reason": (
            "Owner retired this line from all_shipped_chains with no same-line successor; "
            "its slot (writing, second, medium) is now held by claude-sonnet-5-5."
        ),
        "scope": "all_shipped_chains",
        "decision_date": "2026-10-13",
        "evidence_state": "editorial_not_measured",
        "evidence_pointers": ["docs/MODEL-ONBOARDING.md#4-place-routing", "src/coding/model_recommendations.py"],
    },
}


def _canonical_id(model_id: str) -> str:
    return model_id.rsplit("/", 1)[-1].casefold()


def _served_aliases(canonical: str) -> list[str]:
    # Only declared same-mode/tier pointers are bidirectional identities.
    # Astra modes, tiers, snapshots, and fuzzy spellings must not enter here.
    for exact, pointers in EXACT_CONTRACT_POINTER_ALIASES.items():
        if canonical == exact or canonical in pointers:
            return sorted((exact, *pointers))
    return [canonical]


def _superseded_by(canonical: str, inventory_ids: frozenset[str]) -> dict[str, object] | None:
    """Advisory successor link, read from RETIREMENT_DECISIONS only.

    No version string is parsed: an id without a recorded retirement has no
    successor here, however its name compares with another id's. The link
    never changes a disposition or the exit code; it names the successor so
    a reader of the older row does not have to find it by hand.
    `successor_in_inventory` matches the successor's unqualified id or a
    declared served pointer of it; another spelling (a dotted gateway id)
    does not count.
    """
    retirement = RETIREMENT_DECISIONS.get(canonical)
    # A retirement with no same-line successor (an empty `successor`) has no
    # link to offer; its own reason says which model now holds the slot.
    if not retirement or not retirement["successor"]:
        return None
    successor = str(retirement["successor"])
    return {
        "successor": successor,
        "scope": retirement["scope"],
        "decision_date": retirement["decision_date"],
        "successor_in_inventory": any(alias in inventory_ids for alias in _served_aliases(successor)),
        "advisory": True,
    }


def _calibration_resolution(model: str) -> dict[str, str]:
    key = contract_model_id(model)
    family = model_family(model)

    def level(exact: Mapping[str, str], families: Mapping[str, str]) -> str:
        if not model:
            return "missing"
        if key in exact:
            return "exact"
        if family not in ("", "unknown", "generic") and family in families:
            return "family"
        return "generic" if "generic" in families else "missing"

    return {
        "high_effort": level(MODEL_HIGH_EFFORT_CALIBRATIONS, HIGH_EFFORT_CALIBRATIONS),
        "composition": level(MODEL_COMPOSITION_CALIBRATIONS, MAIN_AGENT_COMPOSITION_CALIBRATIONS),
    }


def _placements(aliases: list[str], approved: tuple[str, ...]) -> list[dict[str, object]]:
    placements = []
    for section in _SECTIONS:
        for category, chain in SHIPPED_MODEL_RECOMMENDATIONS[section].items():
            scope = f"{section}:{category}"
            if scope not in approved:
                continue
            for candidate in chain:
                if _canonical_id(candidate["model_alias"]) in aliases:
                    placements.append({
                        "surface": section,
                        "category": category,
                        "model_alias": candidate["model_alias"],
                        "reason": candidate["reasoning"],
                        "reasoning_effort": candidate["reasoning_effort"],
                        "evidence_state": "editorial_not_measured",
                        "evidence_pointers": ["src/coding/model_recommendations.py:SHIPPED_MODEL_RECOMMENDATIONS"],
                    })
    return placements


def _stage(state: str, *pointers: str) -> dict[str, object]:
    return {"state": state, "evidence_pointers": list(pointers)}


def _qualification_row(
    model: str,
    identities: Mapping[str, object],
    read_date: str | None,
    exclusions: Mapping[str, str],
    inventory_ids: frozenset[str] = frozenset(),
) -> dict[str, object]:
    canonical = _canonical_id(model)
    family = model_family(model)
    projection = model_contract_projection(model)
    contract_id = projection["contract_model_id"] if projection else None
    recognition = (
        "exact" if canonical in MODEL_CONTRACTS else
        "family" if family not in ("", "unknown") else
        "generic_fallback" if family == "unknown" else "unknown"
    )
    aliases = _served_aliases(canonical)
    resolution = _calibration_resolution(model)
    # Both halves must have standing; the weaker half describes pair coverage.
    levels = ("missing", "generic", "family", "exact")
    calibration = min(resolution.values(), key=levels.index)
    approval = next((RECOMMENDATION_DECISIONS[a] for a in aliases if a in RECOMMENDATION_DECISIONS), ())
    placements = _placements(aliases, approval)
    retirement = deepcopy(RETIREMENT_DECISIONS.get(canonical, {}))
    decision = deepcopy(QUALIFICATION_HOLDS.get(canonical, {}))
    if retirement and retirement["scope"] == "all_shipped_chains":
        decision = retirement
    exclusion = exclusions.get(model.casefold(), exclusions.get(canonical))
    if exclusion:
        decision = {
            "disposition": "excluded_runtime_incompatible",
            "reason": exclusion,
            "dimension": "runtime_contract",
            "evidence_state": "unmeasured",
            "evidence_pointers": ["caller:--intentional-exclusion"],
            "scope": "caller_inventory",
        }
    if decision:
        disposition = str(decision["disposition"])
        reason = str(decision["reason"])
        evidence_state = str(decision.get("evidence_state", "editorial_not_measured"))
        placements = []
    elif approval:
        disposition = "recommended" if placements else "eligible_not_selected"
        reason = "Reviewed editorial placement; not a role-evaluation measurement."
        evidence_state = "editorial_not_measured"
    else:
        disposition = "unmeasured"
        reason = "No reviewed model-and-role qualification decision; recognition alone cannot promote this id."
        evidence_state = "unmeasured"
    excluded = bool(decision)
    contract_coverage = (
        "intentional_exclusion" if excluded else
        "exact" if projection and projection[_SOURCE_LINEAGE_KEY] == "exact" else
        "declared_inheritance" if projection else "missing"
    )
    price = _price_dimension(model_contract(model), projection)
    evidence = {
        dimension: {"state": "unmeasured", "evidence_pointers": []}
        for dimension in ("quality", "tool_reliability", "latency")
    }
    evidence["cost"] = {
        **price,
        "state": "documented_list" if price["status"] == "documented_list" else "unmeasured",
        "evidence_pointers": ["src/coding/model_contracts.py"] if contract_id else [],
    }
    stages = {
        "recognition_probe": _stage("shipped_metadata", "src/coding/model_routing.py:model_family"),
        "research_dossier": _stage("documented_reference" if contract_id else "not_verified",
                                   "docs/MODEL-ONBOARDING.md#2-research-official-first--four-lanes-in-parallel"),
        "calibration_pair": _stage("shipped_metadata" if calibration in ("exact", "family") else "not_verified",
                                   "src/coding/unit_prompt_protocol.py", "MODEL_OPTI.md"),
        "chain_placement": _stage("editorial_not_measured" if placements else "not_verified",
                                  "src/coding/model_recommendations.py"),
        "price_row": _stage("documented_reference" if contract_id else "not_verified",
                            "src/coding/model_contracts.py"),
        "measurement_pair": _stage("not_verified", "docs/MODEL-ONBOARDING.md#8-close-with-measurement"),
    }
    return {
        "requested_model": model,
        "canonical_model_id": canonical,
        "aliases": list(identities["identities"]),
        "served_aliases": aliases,
        "family": family,
        "recognition_mode": recognition,
        "contract_model_id": contract_id,
        "contract_projection": projection,
        "contract_coverage": contract_coverage,
        "calibration_coverage": "intentional_exclusion" if excluded else calibration,
        "calibration_resolution": resolution,
        "optimization": {
            "status": "calibration_present" if calibration in ("exact", "family") else "not_optimized",
            "evidence_state": evidence_state,
            "stages": stages,
        },
        "recommendation_eligibility": placements,
        "evidence": evidence,
        "evidence_state": evidence_state,
        "disposition": disposition,
        "reason": reason,
        "decision": decision or None,
        "retirement_decisions": [retirement] if retirement else [],
        "superseded_by": _superseded_by(canonical, inventory_ids),
        "inventory_evidence": deepcopy(dict(identities)),
        "inventory_read_date": read_date,
        "model_version_boundary": {
            "canonical_model_id": canonical,
            "contract_model_id": contract_id,
            "projection_provenance": projection[_SOURCE_LINEAGE_KEY] if projection else "missing",
            "pointer_read_date": "2026-09-11" if len(aliases) > 1 else None,
            "qualification_scope": "explicit_model_and_role_only",
        },
    }


def build_model_portfolio_qualification(
    inventory: Mapping[str, object],
    *,
    required_models: Iterable[str] = (),
    intentional_exclusions: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Qualify every supplied id; absent requirements block without invented rows.

    Exclusions are caller-declared runtime-contract exclusions, not empirical
    quality failures. Read dates are supplied provenance, never wall-clock time.
    """
    if not isinstance(inventory, Mapping):
        raise ValueError("model portfolio inventory must be a JSON object")
    _validate_inventory_shape(inventory)
    refs, identities = _inventory_model_refs(inventory)
    record = _inventory_record(inventory, refs, identities)
    read_date = inventory.get("read_date")
    if read_date is not None:
        if not isinstance(read_date, str) or date.fromisoformat(read_date).isoformat() != read_date:
            raise ValueError("inventory read_date must be an ISO date (YYYY-MM-DD)")
    exclusions: dict[str, str] = {}
    if intentional_exclusions is not None:
        if not isinstance(intentional_exclusions, Mapping):
            raise ValueError("intentional exclusions must map model ids to reasons")
        for model, reason in intentional_exclusions.items():
            key = _model_ref(model).casefold()
            if not isinstance(reason, str) or not reason.strip() or len(reason) > 2048 or any(ord(c) < 32 for c in reason):
                raise ValueError("intentional exclusion reason must be non-empty text without control characters (maximum 2048 characters)")
            if key in exclusions and exclusions[key] != reason.strip():
                raise ValueError("conflicting intentional exclusion reasons")
            exclusions[key] = reason.strip()
    required = _normalized_refs(required_models)
    inventory_ids = frozenset(_canonical_id(model) for model in refs)
    rows = [
        _qualification_row(model, identities[model.casefold()], read_date, exclusions, inventory_ids)
        for model in refs
    ]
    by_id = {row["requested_model"].casefold(): row for row in rows}
    required_gaps = []
    for model in required:
        row = by_id.get(model.casefold())
        if row is None or row["disposition"] == "unmeasured":
            required_gaps.append(model)
    counts = {disposition: 0 for disposition in PORTFOLIO_DISPOSITIONS}
    for row in rows:
        counts[row["disposition"]] += 1
    outcome = (
        "required_gaps" if required_gaps else
        f"{record['status']}_inventory" if record["status"] != "observed" else
        "optional_gaps" if counts["unmeasured"] else "qualified"
    )
    comparison = {
        "inventory": {**record, "read_date": read_date},
        "models": rows,
        "requirements": {"required_models": list(required), "intentional_exclusions": dict(sorted(exclusions.items()))},
        "summary": {"total_models": len(rows), "disposition_counts": counts,
                    "required_gaps": required_gaps, "outcome": outcome},
    }
    return {
        "schema_version": MODEL_PORTFOLIO_QUALIFICATION_SCHEMA_VERSION,
        "claim_boundary": MODEL_CONTRACT_COVERAGE_CLAIM_BOUNDARY,
        "comparison": comparison,
        "comparison_digest": _digest(comparison),
        "blocking": bool(required_gaps),
    }
