"""Offline parity audit between OMH skills, base-model value mechanisms, and upstream Hermes skills.

`omh docs hermes-skill-parity [--check] [--json]` renders `omh_hermes_skill_parity/v1`.
It makes no network calls: it audits the live OMH catalog against the pinned
`NousResearch/hermes-agent` bundled (`skills/`) and optional (`optional-skills/`)
inventories recorded in `catalog_types.py` and the reviewed `value_mechanisms.py`
classification.
"""

from __future__ import annotations

from collections import Counter

from ..quality.reported_rate import reported_rate
from .catalog import builtin_definitions, installable_skill_definitions, omh_skill_display_name
from .catalog_types import (
    HERMES_BUNDLED_SKILL_NAMES,
    HERMES_FLOOR_BUNDLED_ALIASES,
    HERMES_OPTIONAL_SKILL_NAMES,
    HermesOptionalSkillLine,
    HermesSkillLine,
)
from .value_mechanisms import (
    VALUE_MECHANISM_PROSE_TEMPLATE_REVIEW,
    VALUE_MECHANISMS,
    value_mechanisms_for_skill,
)

HERMES_SKILL_PARITY_SCHEMA_VERSION = "omh_hermes_skill_parity/v1"
UPSTREAM_HERMES_REPO = "NousResearch/hermes-agent"
UPSTREAM_HERMES_SNAPSHOT_DATE = "2026-11-25"
UPSTREAM_MOVED_TO_OPTIONAL: frozenset[str] = frozenset(
    {"hermes-agent-skill-authoring", "llm-wiki", "opencode"}
)

# Every OMH skill with a direct, known collision against a skill currently
# bundled under upstream Hermes `skills/`. Each entry must carry a
# `HermesSkillLine` naming every listed bundled skill.
REQUIRED_BUNDLED_OVERLAP_BOUNDARIES: dict[str, tuple[str, ...]] = {
    "agent-board": ("sdlc-review",),
    "ai-job-search": ("grounded-citations",),
    "ai-slop-cleaner": ("simplify-code",),
    "app-debugging": ("systematic-debugging",),
    "app-work-intake": ("email-inbox-triage",),
    "biomedical-evidence": ("grounded-citations",),
    "browser-operator": ("computer-use",),
    "code-review": ("sdlc-review", "requesting-code-review"),
    "codebase-onboarding": ("codebase-inspection",),
    "codebase-uml": ("architecture-diagram",),
    "connector-operator": ("email-inbox-triage",),
    "content-operator": ("humanizer",),
    "decision-prototype": ("spike",),
    "doctor": ("hermes-agent",),
    "frontend": ("claude-design", "popular-web-designs"),
    "github-event-ops": ("github",),
    "github-issue-intake": ("github",),
    "img-summary": ("baoyu-infographic",),
    "long-document-reading": ("document-to-action-items",),
    "maestro": ("claude-code", "codex"),
    "materials-package": ("pdf", "docx", "powerpoint", "xlsx", "microsoft-office"),
    "meeting-brief": ("meeting-action-items",),
    "ops-review": ("weekly-review-planning",),
    "research-department": ("competitor-news-monitor", "arxiv"),
    "show-reel": ("manim-video", "ascii-video"),
    "ultraqa": ("dogfood",),
    "verification-gate": ("test-driven-development",),
    "visual-qa": ("dogfood",),
    "web-research": ("grounded-citations", "arxiv", "blocked-page-recovery"),
}

# Skills that moved from `skills/` to `optional-skills/` after the supported
# floor tag must be referenced via `HermesOptionalSkillLine` with conditional
# installation wording rather than unconditional `HermesSkillLine`.
REQUIRED_OPTIONAL_OVERLAP_BOUNDARIES: dict[str, tuple[str, ...]] = {
    "maestro": ("opencode",),
    "skill": ("hermes-agent-skill-authoring",),
    "wiki": ("llm-wiki",),
}

# Reviewed consolidation/retirement review queue derived from the base-model
# sufficiency + upstream Hermes overlap audit. Final retirement requires a
# live 2-model `benchmarks/skill-lift/v1/` run showing no lift.
CONSOLIDATION_CANDIDATES: tuple[dict[str, object], ...] = (
    {
        "group": "hermes-setup-and-readiness",
        "tier": "tier4_setup_readiness",
        "candidates": [
            "parallel-tools",
            "websearch-setup",
            "morning-brief",
            "executor-runtime-readiness",
            "provider-profile-posture",
            "toolbelt-readiness",
            "workspace-audit",
        ],
        "target_surface": "omh-doctor / consolidated setup reference pack",
        "decision_gate": "benchmarks/skill-lift/v1/ (2-model live lift gate)",
    },
    {
        "group": "thin-duplicate-status-and-attachment-cards",
        "tier": "tier5_duplicate_or_thin_card",
        "candidates": [
            "deliverable-package",
            "gateway-intent-card",
            "achievements",
            "ops-observability-card",
        ],
        "target_surface": "omh-materials-package / omh-ops-review / omh-doctor",
        "decision_gate": "benchmarks/skill-lift/v1/ (2-model live lift gate)",
    },
)


def hermes_skill_parity_payload() -> dict[str, object]:
    """Build the deterministic offline `omh_hermes_skill_parity/v1` audit payload."""
    definitions = list(installable_skill_definitions())
    by_name = {definition.name: definition for definition in definitions}
    all_names = {definition.name for definition in builtin_definitions()}
    all_labels = {omh_skill_display_name(name) for name in all_names}

    findings: list[dict[str, str]] = []

    bundled_collisions = sorted(HERMES_BUNDLED_SKILL_NAMES & (all_names | all_labels))
    for name in bundled_collisions:
        findings.append(
            {
                "code": "bundled_name_collision",
                "skill": name,
                "detail": f"Upstream bundled skill {name!r} collides with an OMH catalog name or label.",
            }
        )
    optional_collisions = sorted(HERMES_OPTIONAL_SKILL_NAMES & (all_names | all_labels))
    for name in optional_collisions:
        findings.append(
            {
                "code": "optional_name_collision",
                "skill": name,
                "detail": f"Upstream optional skill {name!r} collides with an OMH catalog name or label.",
            }
        )
    stale_overlap = sorted(HERMES_BUNDLED_SKILL_NAMES & HERMES_OPTIONAL_SKILL_NAMES)
    for name in stale_overlap:
        findings.append(
            {
                "code": "bundled_optional_set_overlap",
                "skill": name,
                "detail": f"Upstream skill {name!r} appears in both bundled and optional inventories.",
            }
        )

    mechanism_counts: Counter[str] = Counter()
    prose_review_labels: list[str] = []
    omh_installable_count = 0
    bundled_deferrals: dict[str, list[str]] = {}
    optional_deferrals: dict[str, list[str]] = {}

    for definition in definitions:
        label = omh_skill_display_name(definition.name)
        if label.startswith("omh-"):
            omh_installable_count += 1
        try:
            mechanisms = value_mechanisms_for_skill(definition.name, allow_retired=False)
        except (KeyError, ValueError) as exc:
            findings.append(
                {
                    "code": "missing_value_mechanism",
                    "skill": definition.name,
                    "detail": str(exc),
                }
            )
            mechanisms = ()
        for mechanism in mechanisms:
            mechanism_counts[mechanism] += 1
        if VALUE_MECHANISM_PROSE_TEMPLATE_REVIEW in mechanisms and label.startswith("omh-"):
            prose_review_labels.append(label)

        own_bundled: list[str] = []
        own_optional: list[str] = []
        for line in definition.do_not_use_when:
            if isinstance(line, HermesOptionalSkillLine):
                own_optional.extend(line.skills)
            elif isinstance(line, HermesSkillLine):
                own_bundled.extend(line.skills)
                moved = sorted(set(line.skills) & UPSTREAM_MOVED_TO_OPTIONAL)
                if moved:
                    findings.append(
                        {
                            "code": "stale_bundled_deferral",
                            "skill": definition.name,
                            "detail": (
                                f"Names moved-to-optional skill(s) {moved} via unconditional HermesSkillLine; "
                                "use HermesOptionalSkillLine."
                            ),
                        }
                    )
        if own_bundled:
            bundled_deferrals[definition.name] = own_bundled
        if own_optional:
            optional_deferrals[definition.name] = own_optional

    for owner, expected in sorted(REQUIRED_BUNDLED_OVERLAP_BOUNDARIES.items()):
        if owner not in by_name:
            findings.append(
                {
                    "code": "unknown_parity_owner",
                    "skill": owner,
                    "detail": f"REQUIRED_BUNDLED_OVERLAP_BOUNDARIES names non-installable skill {owner!r}.",
                }
            )
            continue
        actual = set(bundled_deferrals.get(owner, ()))
        missing = sorted(set(expected) - actual)
        if missing:
            findings.append(
                {
                    "code": "missing_bundled_boundary",
                    "skill": owner,
                    "detail": f"Missing HermesSkillLine deferral for bundled upstream skill(s): {missing}.",
                }
            )

    for owner, expected in sorted(REQUIRED_OPTIONAL_OVERLAP_BOUNDARIES.items()):
        if owner not in by_name:
            findings.append(
                {
                    "code": "unknown_parity_owner",
                    "skill": owner,
                    "detail": f"REQUIRED_OPTIONAL_OVERLAP_BOUNDARIES names non-installable skill {owner!r}.",
                }
            )
            continue
        actual = set(optional_deferrals.get(owner, ()))
        missing = sorted(set(expected) - actual)
        if missing:
            findings.append(
                {
                    "code": "missing_optional_boundary",
                    "skill": owner,
                    "detail": f"Missing HermesOptionalSkillLine deferral for optional upstream skill(s): {missing}.",
                }
            )

    required_bundled_pairs = sum(len(v) for v in REQUIRED_BUNDLED_OVERLAP_BOUNDARIES.values())
    covered_bundled_pairs = sum(
        len(set(expected) & set(bundled_deferrals.get(owner, ())))
        for owner, expected in REQUIRED_BUNDLED_OVERLAP_BOUNDARIES.items()
    )
    non_prose_omh_count = omh_installable_count - len(prose_review_labels)

    return {
        "schema_version": HERMES_SKILL_PARITY_SCHEMA_VERSION,
        "ok": not findings,
        "offline_snapshot_only": True,
        "upstream": {
            "repo": UPSTREAM_HERMES_REPO,
            "snapshot_date": UPSTREAM_HERMES_SNAPSHOT_DATE,
            "bundled_count": len(HERMES_BUNDLED_SKILL_NAMES - HERMES_FLOOR_BUNDLED_ALIASES),
            "floor_alias_count": len(HERMES_FLOOR_BUNDLED_ALIASES),
            "optional_tracked_count": len(HERMES_OPTIONAL_SKILL_NAMES),
            "moved_to_optional": sorted(UPSTREAM_MOVED_TO_OPTIONAL),
        },
        "catalog": {
            "installable_total": len(definitions),
            "omh_installable_total": omh_installable_count,
            "value_mechanism_counts": {k: mechanism_counts.get(k, 0) for k in VALUE_MECHANISMS},
            "prose_template_review_count": len(prose_review_labels),
            "prose_template_review_skills": sorted(prose_review_labels),
            "structured_value_share": reported_rate(
                numerator=non_prose_omh_count,
                denominator=omh_installable_count,
                numerator_of=("non_prose_value_mechanism_omh_skills",),
                denominator_of="installable_omh_prefixed_skills",
                excluded=("ulw_and_dag_engines", "retired_skills"),
            ).to_payload(),
        },
        "upstream_boundaries": {
            "bundled_owners": len(bundled_deferrals),
            "optional_owners": len(optional_deferrals),
            "bundled_overlap_coverage": reported_rate(
                numerator=covered_bundled_pairs,
                denominator=required_bundled_pairs,
                numerator_of=("covered_required_bundled_overlap_pairs",),
                denominator_of="required_bundled_overlap_pairs",
                excluded=("unmapped_optional_skills",),
            ).to_payload(),
        },
        "consolidation_candidates": list(CONSOLIDATION_CANDIDATES),
        "findings": findings,
        "claim_boundary": (
            "Offline parity audit against the pinned upstream Hermes snapshot and reviewed value-mechanism table. "
            "It verifies declared boundaries and catalog classifications only; it does not probe live upstream "
            "repositories or measure with-vs-without base-model lift."
        ),
    }


def hermes_skill_parity_markdown() -> str:
    payload = hermes_skill_parity_payload()
    upstream = payload["upstream"]
    catalog = payload["catalog"]
    boundaries = payload["upstream_boundaries"]
    findings = payload["findings"]
    lines = [
        "# Hermes Skill Parity & Value-Mechanism Audit",
        "",
        f"- Status: {'OK' if payload['ok'] else 'FAILED'} ({len(findings)} finding(s))",
        f"- Upstream snapshot: `{upstream['repo']}` ({upstream['snapshot_date']}, "
        f"{upstream['bundled_count']} bundled + {upstream['floor_alias_count']} floor aliases, "
        f"{upstream['optional_tracked_count']} tracked optional)",
        f"- Installable skills: {catalog['installable_total']} total ({catalog['omh_installable_total']} `omh-*`)",
        f"- Bundled deferral owners: {boundaries['bundled_owners']} | Optional deferral owners: {boundaries['optional_owners']}",
        f"- Prose templates queued for with-vs-without lift review: {catalog['prose_template_review_count']}",
        "",
        "## Value Mechanism Counts",
        "",
        "| Value mechanism | Skills |",
        "| --- | ---: |",
    ]
    for mechanism, count in catalog["value_mechanism_counts"].items():
        lines.append(f"| `{mechanism}` | {count} |")
    if findings:
        lines.extend(["", "## Findings", ""])
        for item in findings:
            lines.append(f"- `{item['code']}` ({item['skill']}): {item['detail']}")
    lines.append("")
    return "\n".join(lines)
