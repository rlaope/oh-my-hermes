"""Assembles the OMH skill catalog and serves it.

The catalog is built by ordered mutation, and that order is the point: the
hand-written definitions come first, then the standalone quality-evidence skill,
then the feature-surface skills, then the native-capability skills. Consumers see
that order in `builtin_definitions()`, and the generated docs and skill files are
byte-compared against it, so reordering this file changes committed artifacts.

The data itself lives next door - `catalog_types` (what a skill is),
`catalog_definitions` (the hand-written skills), `catalog_feature_surfaces`
(template-built skills), and `catalog_harnesses` (runtime contracts). This module
is the assembly and the public surface: every accessor other code imports.
"""

from __future__ import annotations

from ..harness_quality import (
    build_harness_quality_contract,
    unknown_harness_quality_contract,
)

from copy import copy
from functools import lru_cache
from typing import TypedDict

from ..routing.trigger_language_packs import (
    merged_trigger_phrases,
    shipped_trigger_language_packs,
)
from .native_capability_surfaces import (
    native_capability_harnesses,
    native_capability_skill_definitions,
    native_capability_surface_exposures,
)
from .catalog_definitions import _DEFINITIONS
from .catalog_feature_surfaces import _FEATURE_SURFACE_SKILLS
from .catalog_harnesses import (
    _FEATURE_SURFACE_HARNESSES,
    _HARNESSES,
    _PRIMARY_HARNESSES,
    _feature_surface_harness,
)
# Re-exported for import compatibility: 30 modules and the test suite import
# these straight from `catalog`, so the split must not move where they are
# reachable from. They are unused inside this file by design.
from ..paper_learning import (
    PAPER_LEARNING_ACTIONS,
    PAPER_LEARNING_CARD_SCHEMA_VERSION,
    PAPER_LEARNING_COVERAGE_POLICY,
    PAPER_LEARNING_LEVELS,
    PAPER_LEARNING_NOT_OBSERVED,
    PAPER_LEARNING_SOURCE_STATES,
)
from ..routing.materials_cues import OFFICE_FILE_MATERIAL_CATALOG_TRIGGERS
from ..source_finder import (
    SOURCE_ACQUISITION_STATUS_SCHEMA_VERSION,
    SOURCE_CANDIDATE_SCHEMA_VERSION,
    SOURCE_CANDIDATE_SET_SCHEMA_VERSION,
    SOURCE_FINDER_ACQUISITION_STATES,
    SOURCE_FINDER_ACTIONS,
    SOURCE_FINDER_PLAN_SCHEMA_VERSION,
    SOURCE_FINDER_SOURCE_KINDS,
)
from .catalog_types import (
    _CATEGORY_FINAL_CHECKLISTS,
    _CATEGORY_RECOVERY_NOTES,
    _DEFAULT_GOOD_EXAMPLES,
    _GENERAL_FINAL_CHECKLIST,
    _GENERAL_RECOVERY_NOTES,
    _HANDOFF_FINAL_CHECKLIST,
    _HANDOFF_RECOVERY_NOTES,
    _HERMES_CODING_HARNESS_FINAL_CHECKLIST,
    _HERMES_SETUP_FIVE_STEP_BAR,
    _HERMES_SETUP_SKIP_SEMANTICS,
    _HERMES_SETUP_WRITE_BOUNDARY,
    _ROLE_ALIASES,
    _ROLE_BY_CATEGORY,
    _default_final_checklist,
    _default_recovery_notes,
)
from .catalog_types import (
    CODING_INTENTS,
    CODING_INTENT_PRIORITY,
    CODING_INTENT_TERMS,
    CODING_REVIEW_TERMS,
    DECISION_FRONTIER_BUDGET_SCOPE,
    DECISION_FRONTIER_COMPACTION_FAILURE_ACTION,
    DECISION_FRONTIER_CONSENT_GATES,
    DECISION_FRONTIER_DECISION_ID_PREFIX,
    DECISION_FRONTIER_DECISION_STATES,
    DECISION_FRONTIER_HARNESS,
    DECISION_FRONTIER_OMITTED_ANSWER_TRANSITION,
    DECISION_FRONTIER_PARTIAL_ANSWER_POLICY,
    DECISION_FRONTIER_POLICY_SCHEMA_VERSION,
    DECISION_FRONTIER_RECOMMENDATION_POLICY,
    DECISION_FRONTIER_ROUND_UNIT,
    DECISION_FRONTIER_STOP_RULE_ORDER,
    DECISION_FRONTIER_USER_STOP_SCOPE,
    DEEP_INTERVIEW_CLARITY_DIMENSIONS,
    DEEP_INTERVIEW_MAX_ROUNDS,
    DEEP_INTERVIEW_SOFT_CHECK_ROUND,
    DELEGATE_MODEL_LABEL_RULE,
    DELEGATE_PERMISSION_PREFLIGHT_RULE,
    DELEGATE_PROMPT_DISPLAY_RULE,
    DELEGATE_RESUMABLE_SESSION_RULE,
    DELEGATION_TRANSPARENCY_RULES,
    ENGINE_CLOSING_BRIEF_RULE,
    ENGINE_ENTRY_CONFIRMATION_RULE,
    ENGINE_FIT_RECOMMENDATION_RULE,
    ENGINE_FOLLOW_UP_AUTHORITY_RULE,
    ENGINE_INTERJECTION_RESUME_RULE,
    ExpertQuestion,
    HarnessDefinition,
    ProcedureCheck,
    ProcedureStep,
    REASONING_DEMAND_VALUES,
    OMH_DESCRIPTION_PREFIX,
    OMH_SKILL_DISPLAY_NAME_OVERRIDES,
    OMH_SKILL_NAME_PREFIX,
    SkillDefinition,
    SkillExample,
    SURFACE_LIFECYCLE_STAGES,
    SurfaceExposure,
    ULW_ENGINE_SKILL_NAMES,
    ULW_SKILL_NAME_PREFIX,
    _CODING_INTENT_BY_SKILL,
    _feature_surface_skill,
    canonical_hermes_role,
    historical_skill_display_names,
    omh_description,
    omh_skill_display_name,
)

_DEFINITIONS.extend(_FEATURE_SURFACE_SKILLS)


_DEFAULT_SURFACE_PROJECTIONS = ("routable", "installable", "workflow_reference", "capability")
_DEFAULT_SURFACE_PREFERRED_USAGE = (
    "Use as an installed Hermes workflow skill when this explicit workflow is the clearest user-facing handle."
)
# Retired surfaces keep only the reference projection -- the
# `quality-evidence-loop` precedent: the contract exists but is not an
# installed, routable, user-facing skill.
_RETIRED_SURFACE_PROJECTIONS = ("workflow_reference",)
_RETIRED_SURFACE_PREFERRED_USAGE = (
    "Retired workflow engine: the intent now runs as a `ulw-work` capability; keep this contract as a "
    "workflow reference only."
)


def _retired_sibling_preferred_usage(target_home: str) -> str:
    """Preferred-usage line for a skill retired into a sibling skill.

    The engine line above names a capability inside `ulw-work`. A skill folded
    into a sibling has no capability id -- the whole target home is where the
    intent now runs -- so the line names the target's display label instead.
    """
    return (
        f"Retired workflow surface: the intent now runs as `{omh_skill_display_name(target_home)}`; "
        "keep this contract as a workflow reference only."
    )


_SURFACE_EXPOSURES = (
    SurfaceExposure(
        "design-orchestration",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill for broad design ownership before handing a narrowed concern to design-quality-gate, frontend, accessibility-audit, or visual-qa.",
    ),
    SurfaceExposure(
        "quality-evidence-loop",
        "workflow_reference",
        ("workflow_reference",),
        False,
        "operator_reference",
        "Use as agent-facing catalog guidance for QA scenarios, independent review, and source-bound assessment; invoke the quality-evidence CLI only as a backend/operator control plane.",
    ),
    SurfaceExposure(
        "source-finder",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when the user asks to find or classify source candidates before learning, research, materials, or coding work.",
    ),
    SurfaceExposure(
        "paper-learning",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when the user asks to understand a supplied paper or paper PDF by level without dropping section coverage.",
    ),
    SurfaceExposure(
        "long-document-reading",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when the user asks to read, summarize, or process a document that does not fit one read: a very large PDF, contract, manual, or annual report, kept honest by a page-anchored chunk ledger.",
    ),
    SurfaceExposure(
        "automation-blueprint",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when the user asks for recurring automation or scheduled ops planning.",
    ),
    SurfaceExposure(
        "github-event-ops",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask how to triage GitHub PR, issue, review, webhook, or CI events into label, review, or fix-handoff actions without claiming GitHub mutation.",
    ),
    SurfaceExposure(
        "github-issue-intake",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when a public chat report should become a new GitHub issue through classification, a bounded interview, duplicate search, direction confirmation, and an authorized connector handoff without core OMH calling GitHub.",
    ),
    SurfaceExposure(
        "agent-board",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask to coordinate multiple Hermes agents, subagents, roles, handoffs, blockers, heartbeats, or board-shaped collaboration without claiming other agents accepted or completed work.",
    ),
    SurfaceExposure(
        "memory-new",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when the user wants to add new project, product, or durable context memory through capture, review, and approval.",
    ),
    SurfaceExposure(
        "memory-sync",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when the user asks to review stale, duplicate, conflicting, or unresolved (open) memory and skill context.",
    ),
    SurfaceExposure(
        "gateway-intent-card",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask to route, notify, post, or package Discord, Slack, Telegram, webhook, thread, attachment, or silent/status-update gateway intent without claiming delivery.",
    ),
    SurfaceExposure(
        "executor-runtime-readiness",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask whether Codex, Claude Code, Hermes coding, or another runtime has the tools, credentials, worktree posture, and handoff mode needed before dispatch.",
    ),
    SurfaceExposure(
        "deliverable-package",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when the user asks for file deliverable packaging and attachment lifecycle status.",
    ),
    SurfaceExposure(
        "design-quality-gate",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when a visual, web, frontend, deck, PDF, poster, or publishing deliverable must meet a superior design/content/layout QA bar.",
    ),
    SurfaceExposure(
        "frontend",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when a web UI or frontend surface needs design-system, layout, responsive, accessibility, performance, and visual-QA handoff preparation.",
    ),
    SurfaceExposure(
        "accessibility-audit",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when a UI surface needs WCAG, keyboard, focus, screen-reader, target-size, contrast, and reflow audit gates.",
    ),
    SurfaceExposure(
        "visual-qa",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when a rendered web, image, document, or TUI surface needs fresh visual evidence, diff review, and PASS/REVISE/BLOCK gating.",
    ),
    SurfaceExposure(
        "browser-operator",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask to open URLs, click pages, log in, fill forms, capture blockers, or supervise browser interactions without claiming browser execution.",
    ),
    SurfaceExposure(
        "workspace-file-operator",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask to list, search, organize, copy, move, rename, archive, or delete local files and folders without claiming filesystem mutation.",
    ),
    SurfaceExposure(
        "command-operator",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask to prepare or supervise terminal, shell, CLI, package-manager, or test commands without claiming command execution.",
    ),
    SurfaceExposure(
        "connector-operator",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask to prepare or supervise external app, SaaS, email, ticket, calendar, CRM, or connector actions without claiming provider execution.",
    ),
    SurfaceExposure(
        "live-info-operator",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask to prepare or supervise read-only weather, finance, sports, map, place, exchange-rate, or time-zone lookups without claiming live data retrieval.",
    ),
    SurfaceExposure(
        "external-connector-readiness",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask whether an external plugin, connector, API, multimodal route, or live-data tool is ready enough to adopt, route, or trial without claiming provider execution.",
    ),
    SurfaceExposure(
        "prompt-import-readiness",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask whether external CLI-agent prompt files can be safely reviewed, normalized, and exposed as Hermes slash-command candidates without claiming prompt mutation.",
    ),
    SurfaceExposure(
        "physical-device-readiness",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use when physical device workflows need a safety envelope, gates, approval, dry-run, and observed-only trial boundary.",
    ),
    SurfaceExposure(
        "content-operator",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask for publish-ready writing, rewriting, summarization, translation, release notes, newsletter, customer copy, or email-draft work with audience, tone, source, and review gates.",
    ),
    SurfaceExposure(
        "media-input-operator",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask to prepare or supervise audio/video transcription, YouTube/video summaries, OCR, screenshot text extraction, receipt image parsing, meeting recordings, timestamps, or clip summaries without claiming media access, transcript, OCR, or parsed-field evidence.",
    ),
    SurfaceExposure(
        "data-analysis",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask to analyze supplied CSV, JSON, logs, tables, or metric-like data with schema, method, and hallucination guards.",
    ),
    SurfaceExposure(
        "build-failure-triage",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when failing build, lint, typecheck, test, CI, or DCO evidence needs minimal-fix triage.",
    ),
    SurfaceExposure(
        "voice-operator",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when voice, mobile, dictated, or short commands need normalization, ambiguity checks, and safe confirmation before selecting a concrete workflow.",
    ),
    SurfaceExposure(
        "toolbelt-readiness",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when users ask which plugins, MCP servers, CLIs, APIs, credentials, or external connectors a workflow needs before it can run.",
    ),
    SurfaceExposure(
        "harness-session-inventory",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when operators need a cross-harness session, MCP config, connector, wrapper, and worktree inventory with drift boundaries.",
    ),
    SurfaceExposure(
        "ops-observability-card",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when operators need an evidence-bounded command-board for telemetry, supplied metric-provider payloads, and service-quality gaps.",
    ),
    SurfaceExposure(
        "achievements",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when the user asks about unlocked hermes-achievements badges, tiers, recent unlocks, or badge progress.",
    ),
    SurfaceExposure(
        "agent-ops-review",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when a manager wants quality, blockers, next actions, and throughput guidance for AI-agent work.",
    ),
    SurfaceExposure(
        "agent-debug",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when an agent run is stuck, looping, drifting, or failing repeatedly and needs evidence-bounded diagnosis plus contained recovery guidance.",
    ),
    SurfaceExposure(
        "failure-signal-audit",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when operators need to find swallowed errors, dangerous fallbacks, propagation gaps, and false-green claims before routing remediation.",
    ),
    SurfaceExposure(
        "instinct-ledger",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when repeated lessons should become reviewed, confidence-scored project or global instinct candidates without automatic hook-based learning or mutation.",
    ),
    SurfaceExposure(
        "skill-scout",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill before creating, forking, installing, or adapting a skill so operators can compare candidates and risks first.",
    ),
    SurfaceExposure(
        "skill-health",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when operators need a portfolio health dashboard for skills, generated surfaces, failure-pattern signals, pending amendments, and safe improvement actions.",
    ),
    SurfaceExposure(
        "workflow-learning",
        "workflow_skill",
        ("routable", "installable", "playbook", "harness", "workflow_reference", "capability"),
        True,
        "primary_workflow_skill",
        "Use as an installed Hermes workflow skill when the user wants to learn from a workflow run, review an improvement candidate, create a regression case, or export a redacted review bundle.",
    ),
    # The ULW workflow engines, materialized as explicit rows so each
    # engine's lifecycle stage is answerable from the exposure table instead of
    # falling through `_default_surface_exposure()`. For the canonical
    # engines every field other than `lifecycle_stage` must stay byte-identical
    # to that default -- `tests/test_ulw_inventory.py` pins the equality -- so
    # a lifecycle move is a one-row edit here, never a behavior change smuggled
    # through a default. The four retired engines (#954 stage 5) use the
    # retired shape declared above.
    SurfaceExposure(
        "context",
        "direct_skill",
        _DEFAULT_SURFACE_PROJECTIONS,
        True,
        "primary_workflow_skill",
        _DEFAULT_SURFACE_PREFERRED_USAGE,
        lifecycle_stage="canonical",
    ),
    SurfaceExposure(
        "deep-interview",
        "direct_skill",
        _DEFAULT_SURFACE_PROJECTIONS,
        True,
        "primary_workflow_skill",
        _DEFAULT_SURFACE_PREFERRED_USAGE,
        lifecycle_stage="canonical",
    ),
    SurfaceExposure(
        "research",
        "direct_skill",
        _DEFAULT_SURFACE_PROJECTIONS,
        True,
        "primary_workflow_skill",
        _DEFAULT_SURFACE_PREFERRED_USAGE,
        lifecycle_stage="canonical",
    ),
    SurfaceExposure(
        "ralplan",
        "direct_skill",
        _DEFAULT_SURFACE_PROJECTIONS,
        True,
        "primary_workflow_skill",
        _DEFAULT_SURFACE_PREFERRED_USAGE,
        lifecycle_stage="canonical",
    ),
    SurfaceExposure(
        "ultrawork",
        "direct_skill",
        _DEFAULT_SURFACE_PROJECTIONS,
        True,
        "primary_workflow_skill",
        _DEFAULT_SURFACE_PREFERRED_USAGE,
        lifecycle_stage="canonical",
    ),
    SurfaceExposure(
        "maestro",
        "direct_skill",
        _DEFAULT_SURFACE_PROJECTIONS,
        True,
        "primary_workflow_skill",
        _DEFAULT_SURFACE_PREFERRED_USAGE,
        lifecycle_stage="canonical",
    ),
    # The four retired engines (#954 stage 5, shipped with a window=0
    # maintainer decision: canonical -> retired directly, no alias or warning
    # release in between). Each keeps its `SkillDefinition` and its
    # `workflow_reference` projection (P2: retirement is an exposure change,
    # not a deletion), keeps `compatibility_alias=True` so a stale workflow
    # hint resolves as a compatibility concern, and names its `ulw-work`
    # target home. Rollback is a one-row edit back to the canonical shape;
    # `tests/test_ulw_retirement.py` exercises it per contract.
    SurfaceExposure(
        "ralph",
        "direct_skill",
        _RETIRED_SURFACE_PROJECTIONS,
        False,
        "workflow_reference",
        _RETIRED_SURFACE_PREFERRED_USAGE,
        compatibility_alias=True,
        lifecycle_stage="retired",
        target_home="ultrawork",
        migration_release="1.0.7",
    ),
    SurfaceExposure(
        "team",
        "direct_skill",
        _RETIRED_SURFACE_PROJECTIONS,
        False,
        "workflow_reference",
        _RETIRED_SURFACE_PREFERRED_USAGE,
        compatibility_alias=True,
        lifecycle_stage="retired",
        target_home="ultrawork",
        migration_release="1.0.7",
    ),
    SurfaceExposure(
        "loop",
        "direct_skill",
        _DEFAULT_SURFACE_PROJECTIONS,
        True,
        "primary_workflow_skill",
        _DEFAULT_SURFACE_PREFERRED_USAGE,
        lifecycle_stage="canonical",
    ),
    SurfaceExposure(
        "ultragoal",
        "direct_skill",
        _RETIRED_SURFACE_PROJECTIONS,
        False,
        "workflow_reference",
        _RETIRED_SURFACE_PREFERRED_USAGE,
        compatibility_alias=True,
        lifecycle_stage="retired",
        target_home="ultrawork",
        migration_release="1.0.7",
    ),
    SurfaceExposure(
        "ultraprocess",
        "direct_skill",
        _RETIRED_SURFACE_PROJECTIONS,
        False,
        "workflow_reference",
        _RETIRED_SURFACE_PREFERRED_USAGE,
        compatibility_alias=True,
        lifecycle_stage="retired",
        target_home="ultrawork",
        migration_release="1.0.7",
    ),
    SurfaceExposure(
        "ultraqa",
        "direct_skill",
        _DEFAULT_SURFACE_PROJECTIONS,
        True,
        "primary_workflow_skill",
        _DEFAULT_SURFACE_PREFERRED_USAGE,
        lifecycle_stage="canonical",
    ),
    SurfaceExposure(
        "ultraperf",
        "direct_skill",
        _DEFAULT_SURFACE_PROJECTIONS,
        True,
        "primary_workflow_skill",
        _DEFAULT_SURFACE_PREFERRED_USAGE,
        lifecycle_stage="canonical",
    ),
    # Three non-engine skills folded into a stronger sibling (#1691). Each was
    # a strict subset of its target home -- the target produces the same
    # outputs plus more -- so the pair cost two always-loaded bodies for one
    # job. The retirement shape is the one the engines above use: the
    # `SkillDefinition` stays, the body stops rendering, the contract survives
    # as a `workflow_reference`, and rollback is a one-row edit back to the
    # default shape.
    #
    # Two things differ from the engine rows. The target home is a sibling
    # SKILL, not a capability inside `ulw-work`, so there is no capability id
    # to name and the preferred-usage line names the target instead. And the
    # cue vocabulary migrates by folding each retired trigger into the target
    # home's own trigger table rather than through `routing/ulw_alias.py`:
    # that resolver returns an unconditional high-confidence dispatch on a
    # contained cue, which is right for distinctive engine names and wrong for
    # bare words like `benchmark` and `latency`. Folded triggers stay inside
    # ordinary catalog scoring, where they compete instead of pre-empting.
    SurfaceExposure(
        "performance-goal",
        "direct_skill",
        _RETIRED_SURFACE_PROJECTIONS,
        False,
        "workflow_reference",
        _retired_sibling_preferred_usage("ultraperf"),
        compatibility_alias=True,
        lifecycle_stage="retired",
        target_home="ultraperf",
        migration_release="2.0.4",
    ),
    SurfaceExposure(
        "best-practice-research",
        "direct_skill",
        _RETIRED_SURFACE_PROJECTIONS,
        False,
        "workflow_reference",
        _retired_sibling_preferred_usage("web-research"),
        compatibility_alias=True,
        lifecycle_stage="retired",
        target_home="web-research",
        migration_release="2.0.4",
    ),
    SurfaceExposure(
        "autoresearch-goal",
        "direct_skill",
        _RETIRED_SURFACE_PROJECTIONS,
        False,
        "workflow_reference",
        _retired_sibling_preferred_usage("research"),
        compatibility_alias=True,
        lifecycle_stage="retired",
        target_home="research",
        migration_release="2.0.4",
    ),
)


_HARNESSES.extend(_FEATURE_SURFACE_HARNESSES)


_DEFINITIONS.extend(native_capability_skill_definitions(_feature_surface_skill))
_HARNESSES.extend(native_capability_harnesses(_feature_surface_harness))
_PRIMARY_HARNESSES.update(
    {
        "decision-recall": "decision-recall",
        "run-efficiency": "run-efficiency",
        "provider-profile-posture": "provider-profile-posture",
    }
)
_CODING_INTENT_BY_SKILL.update(
    {
        "decision-recall": "planning",
        "run-efficiency": "planning",
        "provider-profile-posture": "planning",
    }
)
_SURFACE_EXPOSURES = (*_SURFACE_EXPOSURES, *native_capability_surface_exposures(SurfaceExposure))


def builtin_definitions() -> list[SkillDefinition]:
    return list(_builtin_definitions_cached())


def routable_definitions() -> list[SkillDefinition]:
    return _projected_definitions("routable")


def installable_skill_definitions() -> list[SkillDefinition]:
    return [
        definition
        for definition in _builtin_definitions_cached()
        if surface_exposure_for_skill(definition.name).install_visibility
    ]


def capability_definitions() -> list[SkillDefinition]:
    return _projected_definitions("capability")


def workflow_reference_definitions() -> list[SkillDefinition]:
    return _projected_definitions("workflow_reference")


def routable_skill_names() -> tuple[str, ...]:
    return tuple(definition.name for definition in routable_definitions())


def installable_skill_names() -> tuple[str, ...]:
    return tuple(definition.name for definition in installable_skill_definitions())


ULTRAWORK_HERMES_CATEGORY = "ultrawork"
HERMES_CATEGORY_FALLBACK = "workflow"


def hermes_skill_category(name: str) -> str:
    """The Hermes dashboard group a skill installs under.

    Hermes derives a skill's category from DIRECTORY STRUCTURE, not from
    frontmatter: `tools/skills_tool.py::_get_category_from_path` takes the path
    relative to each configured skills dir and uses the first path component
    only when the relative path has three or more parts. A flat
    `<skills_dir>/<skill>/SKILL.md` install therefore resolves to no category at
    all, and the startup banner filed every OMH skill under "general". Installs
    are nested one level deeper -- `<skills_dir>/<category>/<skill>/SKILL.md` --
    so the group a reader sees is a group OMH chose.

    The group is deliberately NOT `SkillDefinition.category`. That field is the
    catalog's fine-grained phase vocabulary (41 values across ~100 skills), and
    one banner line per value is not a dashboard. `hermes_role` is the coarse
    axis the product already documents in `docs/ROLES.md`, so it is what the
    directories mirror.

    The ULW engines are the one carve-out: they span six catalog categories and
    five roles, but a user reaching for them is reaching for the ULW engine
    family by name. Grouping them under `ultrawork` is what makes the banner
    able to say so. Membership reuses `ULW_ENGINE_SKILL_NAMES`, the same list
    that owns the `ulw-` label prefix, so a skill cannot be a ULW engine in one
    surface and not the other.
    """
    text = name.strip()
    if text in ULW_ENGINE_SKILL_NAMES:
        return ULTRAWORK_HERMES_CATEGORY
    return _hermes_category_by_skill().get(text, HERMES_CATEGORY_FALLBACK)


def hermes_skill_categories() -> tuple[str, ...]:
    """Every category an installable skill lands in, sorted."""
    return tuple(
        sorted({hermes_skill_category(name) for name in installable_skill_names()})
    )


def omh_skill_install_path(name: str) -> str:
    """Posix relative path of a skill's install directory under the skills dir."""
    return f"{hermes_skill_category(name)}/{omh_skill_display_name(name)}"


@lru_cache(maxsize=1)
def _hermes_category_by_skill() -> dict[str, str]:
    return {definition.name: definition.hermes_role for definition in _builtin_definitions_cached()}


def surface_exposure_for_skill(name: str) -> SurfaceExposure:
    return _surface_exposure_by_name().get(name, _default_surface_exposure(name))


def skill_exposure_payload(name: str) -> dict[str, object]:
    exposure = surface_exposure_for_skill(name)
    return {
        "exposure": exposure.exposure,
        "projections": list(exposure.projections),
        "install_visibility": exposure.install_visibility,
        "docs_visibility": exposure.docs_visibility,
        "preferred_usage": exposure.preferred_usage,
        "compatibility_alias": exposure.compatibility_alias,
        "lifecycle_stage": exposure.lifecycle_stage,
        "target_home": exposure.target_home,
        "migration_release": exposure.migration_release,
    }


ULW_INVENTORY_SCHEMA_VERSION = "omh_ulw_inventory/v1"

# Reader-facing enumeration order for the workflow engines: the request
# pipeline (clarify -> research -> plan -> execute -> verify -> optimize), the
# same order the English README table has always used. Membership is pinned to
# `ULW_ENGINE_SKILL_NAMES` by `ulw_inventory_payload()` itself, so adding or
# dropping an engine in only one of the two fails loudly.
_ULW_ENGINE_ORDER = (
    "context",
    "deep-interview",
    "research",
    "ralplan",
    "ultrawork",
    "maestro",
    "ralph",
    "team",
    "loop",
    "ultragoal",
    "ultraprocess",
    "ultraqa",
    "ultraperf",
)

# Reader-facing copy per engine. `summary` is the English README table cell;
# `site_*` feed the generated site region (`omh docs ulw-site`). Localized row
# prose stays hand-maintained by decision -- these are the English projections
# only. Data, not derivation: catalog descriptions are contract prose, and the
# marketing surfaces deliberately say less.
class UlwEnginePresentation(TypedDict):
    summary: str
    site_tag: str
    site_title: str
    site_body: str
    site_cues: tuple[str, ...]


class UlwEngineSite(TypedDict):
    i18n_stem: str
    tag: str
    title: str
    body: str
    cues: list[str]


class UlwEnginePayload(TypedDict):
    canonical: str
    display_name: str
    historical_display_names: list[str]
    lifecycle_stage: str
    target_home: str | None
    migration_release: str | None
    summary: str
    site: UlwEngineSite


class UlwInventoryCounts(TypedDict):
    canonical: int
    alias: int
    retired: int
    total: int


class UlwInventoryPayload(TypedDict):
    schema_version: str
    canonical_engines: list[UlwEnginePayload]
    alias_engines: list[UlwEnginePayload]
    retired_engines: list[UlwEnginePayload]
    counts: UlwInventoryCounts


_ULW_ENGINE_PRESENTATIONS: dict[str, UlwEnginePresentation] = {
    "context": {
        "summary": (
            "Aligns reviewed project terms, captures confirmed candidates, and interviews the next "
            "decision frontier without giving terminology routing authority."
        ),
        "site_tag": "Terminology alignment",
        "site_title": "Context",
        "site_body": "Aligns the words a repository uses before plans and handoffs.",
        "site_cues": ("ulw-context", "review project terms"),
    },
    "deep-interview": {
        "summary": "Asks one question at a time until it knows exactly what you want.",
        "site_tag": "Clarification",
        "site_title": "Deep Interview",
        "site_body": "One question at a time until the brief is clear.",
        "site_cues": ("deep-interview", "clarify"),
    },
    "research": {
        "summary": "Digs through real code and the live web, keeps sources, and verifies anything doubtful.",
        "site_tag": "Decision grounding",
        "site_title": "Research",
        "site_body": "Reference implementations, live web evidence, verified claims.",
        "site_cues": ("web research", "source-backed research"),
    },
    "ralplan": {
        "summary": "Builds a reviewed plan: options compared, risks named, done-criteria agreed.",
        "site_tag": "Reviewed plan",
        "site_title": "Ralplan",
        "site_body": "Consensus planning with review gates.",
        "site_cues": ("ralplan", "consensus plan"),
    },
    "ultrawork": {
        "summary": "Runs an accepted plan in parallel lanes that never touch the same file.",
        "site_tag": "Parallel delivery",
        "site_title": "Ultrawork",
        "site_body": "Splits an accepted plan into disjoint lanes.",
        "site_cues": ("ultrawork", "parallel work"),
    },
    "maestro": {
        "summary": (
            "Runs a delegated task on Claude Code or Codex — prompt composed from the CLI's own "
            "installed skills, spawned live with a dock row and a steerable session."
        ),
        "site_tag": "External handoff",
        "site_title": "Maestro",
        "site_body": "Runs the work on Claude Code or Codex, spawned live with a steerable session.",
        "site_cues": ("ulw-maestro", "coding handoff"),
    },
    "ralph": {
        "summary": "One owner grinds a task to done — build, verify, review, repeat.",
        "site_tag": "Drive to done",
        "site_title": "Ralph",
        "site_body": "One owner drives a task to done.",
        "site_cues": ("ralph", "finish until done"),
    },
    "team": {
        "summary": "Multiple workers, one task list, no collisions.",
        "site_tag": "Coordination",
        "site_title": "Team",
        "site_body": "N coordinated workers on one shared task list.",
        "site_cues": ("team", "parallel agents"),
    },
    "loop": {
        "summary": "Cycles plan → build → review until the goal actually passes.",
        "site_tag": "Goal loop",
        "site_title": "Loop",
        "site_body": "Interview → plan → research → build → review.",
        "site_cues": ("loop", "long horizon goal"),
    },
    "ultragoal": {
        "summary": "Long-running goals with checkpoints — survives lost context, resumes where it stopped.",
        "site_tag": "Durable goals",
        "site_title": "Ultragoal",
        "site_body": "A checkpointed ledger survives context loss.",
        "site_cues": ("ultragoal", "goal ledger"),
    },
    "ultraprocess": {
        "summary": "Takes one task all the way from research to an open PR.",
        "site_tag": "Task to PR",
        "site_title": "Ultraprocess",
        "site_body": "One clean plan-to-PR cycle.",
        "site_cues": ("ultraprocess", "end-to-end process"),
    },
    "ultraqa": {
        "summary": "Attacks the build with hostile scenarios and fixes what breaks.",
        "site_tag": "Adversarial QA",
        "site_title": "UltraQA",
        "site_body": "Hostile scenarios, end-to-end runs, release QA.",
        "site_cues": ("ultraqa", "release qa"),
    },
    "ultraperf": {
        "summary": "Measures where it is actually slow or expensive, then fixes one hot path at a time.",
        "site_tag": "Measured optimization",
        "site_title": "Ultraperf",
        "site_body": "Finds where the system is actually slow, leaking, or expensive.",
        "site_cues": ("ultraperf", "find the bottleneck"),
    },
}


def ulw_inventory_payload() -> UlwInventoryPayload:
    """Single producer for the ULW engine inventory and per-engine lifecycle state.

    Every downstream ULW surface derives from this payload: the release-drift
    count metrics, the generated site region (`omh docs ulw-site`), the
    generated English README table (`omh docs ulw-inventory`), and the plugin
    bundle parity test. Two producers that can disagree is exactly the
    site-says-eleven-README-says-twelve defect this exists to end.
    """
    if set(_ULW_ENGINE_ORDER) != set(ULW_ENGINE_SKILL_NAMES) or len(_ULW_ENGINE_ORDER) != len(
        ULW_ENGINE_SKILL_NAMES
    ):
        raise ValueError(
            "ULW inventory order drifted from ULW_ENGINE_SKILL_NAMES; "
            "update _ULW_ENGINE_ORDER in src/skills/catalog.py"
        )
    engines: list[UlwEnginePayload] = []
    for name in _ULW_ENGINE_ORDER:
        exposure = surface_exposure_for_skill(name)
        if exposure.lifecycle_stage not in SURFACE_LIFECYCLE_STAGES:
            raise ValueError(f"unknown lifecycle stage for {name}: {exposure.lifecycle_stage}")
        presentation = _ULW_ENGINE_PRESENTATIONS[name]
        display_name = omh_skill_display_name(name)
        engines.append(
            {
                "canonical": name,
                "display_name": display_name,
                "historical_display_names": list(historical_skill_display_names(name)),
                "lifecycle_stage": exposure.lifecycle_stage,
                "target_home": exposure.target_home,
                "migration_release": exposure.migration_release,
                "summary": presentation["summary"],
                "site": {
                    "i18n_stem": display_name.removeprefix(ULW_SKILL_NAME_PREFIX),
                    "tag": presentation["site_tag"],
                    "title": presentation["site_title"],
                    "body": presentation["site_body"],
                    "cues": list(presentation["site_cues"]),
                },
            }
        )
    canonical_engines = [engine for engine in engines if engine["lifecycle_stage"] == "canonical"]
    alias_engines = [engine for engine in engines if engine["lifecycle_stage"] in {"alias", "warning"}]
    # Retired engines are enumerated separately, never silently dropped: the
    # drift gate reads all three lists, so a stage flip that loses an engine
    # from every list fails the total-count parity below.
    retired_engines = [engine for engine in engines if engine["lifecycle_stage"] == "retired"]
    return {
        "schema_version": ULW_INVENTORY_SCHEMA_VERSION,
        "canonical_engines": canonical_engines,
        "alias_engines": alias_engines,
        "retired_engines": retired_engines,
        "counts": {
            "canonical": len(canonical_engines),
            "alias": len(alias_engines),
            "retired": len(retired_engines),
            "total": len(engines),
        },
    }


# The `ulw-work` capability each retired engine's intent now runs as. Kept in
# the catalog (not derived from `src/quality/ulw_equivalence.py`) because
# routing must not import the quality gate; `tests/test_ulw_retirement.py`
# pins this table against the equivalence cases so the two cannot disagree.
ULW_RETIRED_CAPABILITIES = {
    "team": "coordinated_scope",
    "ultraprocess": "delivery_boundary",
    "ralph": "single_owner_persistence",
    "ultragoal": "durable_checkpoint",
}


def retired_ulw_engine_names() -> tuple[str, ...]:
    """Canonical names of ULW engines whose lifecycle stage is `retired`."""
    return tuple(
        engine["canonical"] for engine in ulw_inventory_payload()["retired_engines"]
    )


def retired_ulw_engine_definitions() -> list[SkillDefinition]:
    names = set(retired_ulw_engine_names())
    return [definition for definition in _builtin_definitions_cached() if definition.name in names]


def retired_skill_names() -> tuple[str, ...]:
    """Canonical names of every skill whose lifecycle stage is `retired`.

    Read off the exposure table rather than the ULW inventory, which only
    enumerates the engines in `ULW_ENGINE_SKILL_NAMES`: a skill folded into a
    non-engine sibling (#1691) is retired by the same row shape but is invisible
    to `retired_ulw_engine_names()`. The two are kept separate on purpose --
    the ULW-derived one feeds the engine inventory surfaces (README and site
    regions, drift counts, the capability equivalence table), which mean the
    engines specifically; this one feeds label resolution, the migration error,
    and doctor, which mean every retired contract.
    """
    return tuple(
        exposure.name
        for exposure in _SURFACE_EXPOSURES
        if exposure.lifecycle_stage == "retired"
    )


def retired_display_names() -> dict[str, str]:
    """Map every current and historical display label of a retired skill to its canonical name.

    Consulted after `_canonical_skill_by_display_name()` misses: retirement
    narrows a skill out of the routable projection, which ends ordinary label
    resolution, so a stale label must produce a named migration error instead
    of a silent miss.
    """
    mapping: dict[str, str] = {}
    for name in retired_skill_names():
        mapping[name] = name
        mapping[omh_skill_display_name(name)] = name
        for label in historical_skill_display_names(name):
            mapping[label] = name
    return mapping


@lru_cache(maxsize=1)
def _canonical_by_skill_label() -> dict[str, str]:
    definitions = _builtin_definitions_cached()
    mapping = {omh_skill_display_name(definition.name): definition.name for definition in definitions}
    for definition in definitions:
        for label in historical_skill_display_names(definition.name):
            mapping.setdefault(label, definition.name)
    return mapping


def canonical_skill_for_label(label: str) -> str:
    """Canonical name of the OMH skill a host loaded as `label`, or "" when the catalog never rendered it.

    This is how a reader decides that a loaded skill is OMH's: by the label the
    catalog renders into `name:`, not by anything in the description. Every
    catalog definition counts, retired ones included, under its current label
    and every label an earlier release rendered (`omh-ultrawork`,
    `ulw-ultrawork`, `ulw-team`), so a session recorded before a rename or a
    retirement still resolves. Current labels win a collision. A bare canonical
    name (`plan`, `team`) is deliberately not a label: it is an ordinary word
    another product's skill can carry.
    """
    return _canonical_by_skill_label().get(label.strip(), "")


def retired_skill_migration_error(label: str) -> dict[str, str]:
    """Named migration error for a retired skill label or tap path.

    Returns an empty dict when the label names no retired skill. The message is
    informational migration copy, not a deprecation warning: the intent now
    runs as the named `ulw-work` capability, or -- for a skill folded into a
    sibling rather than into an engine capability -- as the target home skill.
    """
    text = label.strip()
    canonical = retired_display_names().get(text, "")
    if not canonical:
        tail = text.rstrip("/").rsplit("/", 1)[-1]
        canonical = retired_display_names().get(tail, "")
    if not canonical:
        return {}
    if canonical not in ULW_RETIRED_CAPABILITIES:
        return _retired_sibling_migration_error(canonical)
    capability = ULW_RETIRED_CAPABILITIES[canonical]
    display = omh_skill_display_name(canonical)
    return {
        "error": "retired_skill",
        "retired_contract_id": canonical,
        "retired_display_name": display,
        "target_contract_id": "ultrawork",
        "target_display_name": omh_skill_display_name("ultrawork"),
        "selected_capability": capability,
        "message": (
            f"`{display}` is retired; this intent now runs as `ulw-work` capability "
            f"`{capability}`. Install or invoke `ulw-work` (canonical `ultrawork`) instead."
        ),
    }


def _retired_sibling_migration_error(canonical: str) -> dict[str, str]:
    """Migration error for a skill retired into a sibling skill (#1691).

    No `selected_capability` key: the intent moved to a whole target home, not
    to one capability inside `ulw-work`, and inventing a capability id here
    would put a name in diagnostics that no capability table defines.
    """
    exposure = surface_exposure_for_skill(canonical)
    target = exposure.target_home or ""
    display = omh_skill_display_name(canonical)
    target_display = omh_skill_display_name(target) if target else ""
    return {
        "error": "retired_skill",
        "retired_contract_id": canonical,
        "retired_display_name": display,
        "target_contract_id": target,
        "target_display_name": target_display,
        "message": (
            f"`{display}` is retired; this intent now runs as `{target_display}`. "
            f"Install or invoke `{target_display}` (canonical `{target}`) instead."
        ),
    }


def builtin_harnesses() -> list[HarnessDefinition]:
    return list(_builtin_harnesses_cached())


@lru_cache(maxsize=1)
def _builtin_definitions_cached() -> tuple[SkillDefinition, ...]:
    return _with_shipped_trigger_packs(tuple(_DEFINITIONS))


def _with_shipped_trigger_packs(definitions: tuple[SkillDefinition, ...]) -> tuple[SkillDefinition, ...]:
    """Fold the repo-shipped trigger language packs into the catalog itself.

    A shipped pack is product data, not local configuration, so its phrases
    join the catalog before anything reads it: scoring, the rendered `SKILL.md`
    trigger lists, and the generated workflow docs all see one trigger table
    rather than an English one plus a hidden per-language side table. Phrases
    append after the authored ones and repeat phrases are dropped, so a pack
    can only widen what a skill answers to, never reorder or replace it.

    User packs deliberately do NOT merge here -- see
    `routing/trigger_language_packs.py` for why local config stops at the
    scoring layer.
    """
    known_skills = frozenset(definition.name for definition in definitions)
    packs = shipped_trigger_language_packs(known_skills)
    if not packs:
        return definitions
    phrases_by_skill = merged_trigger_phrases(packs)
    if not phrases_by_skill:
        return definitions
    merged: list[SkillDefinition] = []
    for definition in definitions:
        added = tuple(
            phrase
            for phrase in phrases_by_skill.get(definition.name, ())
            if phrase not in definition.triggers
        )
        # Packs merge in language-code order, and `id` sorts before `ja`. The
        # SKILL.md description and the capability row show only a skill's
        # first triggers, so a phrase written wholly in ASCII goes after every
        # pack phrase that is not: a Latin-script pack then takes none of the
        # slots the Hangul, Kana and Han phrases already had.
        extra = tuple(phrase for phrase in added if not phrase.isascii()) + tuple(
            phrase for phrase in added if phrase.isascii()
        )
        if not extra:
            merged.append(definition)
            continue
        # `copy.copy` rather than `dataclasses.replace`: the definition is
        # already assembled, and `__post_init__` is not idempotent -- rerunning
        # it would re-apply `omh_description` and push an already-canonical
        # `hermes_role` through the alias table a second time. A pack only ever
        # widens the trigger tuple, so copy the finished object and set that
        # one field, the same way `__post_init__` sets its own.
        widened = copy(definition)
        object.__setattr__(widened, "triggers", definition.triggers + extra)
        merged.append(widened)
    return tuple(merged)


@lru_cache(maxsize=1)
def _surface_exposure_by_name() -> dict[str, SurfaceExposure]:
    return {exposure.name: exposure for exposure in _SURFACE_EXPOSURES}


def _default_surface_exposure(name: str) -> SurfaceExposure:
    return SurfaceExposure(
        name,
        "direct_skill",
        _DEFAULT_SURFACE_PROJECTIONS,
        True,
        "primary_workflow_skill",
        _DEFAULT_SURFACE_PREFERRED_USAGE,
    )


def _projected_definitions(projection: str) -> list[SkillDefinition]:
    return list(_projected_definitions_cached(projection))


@lru_cache(maxsize=8)
def _projected_definitions_cached(projection: str) -> tuple[SkillDefinition, ...]:
    return tuple(
        definition
        for definition in _builtin_definitions_cached()
        if projection in surface_exposure_for_skill(definition.name).projections
    )


@lru_cache(maxsize=1)
def _builtin_harnesses_cached() -> tuple[HarnessDefinition, ...]:
    return tuple(_HARNESSES)


@lru_cache(maxsize=1)
def _harnesses_by_name() -> dict[str, HarnessDefinition]:
    return {harness.name: harness for harness in _builtin_harnesses_cached()}


def harness_definition(name: str) -> HarnessDefinition:
    return _harnesses_by_name()[name]


def harness_quality_contract(name: str) -> dict[str, object]:
    try:
        harness = harness_definition(name)
    except KeyError:
        return unknown_harness_quality_contract(name)
    return build_harness_quality_contract(
        harness=harness.name,
        quality_tier=harness.quality_tier,
        quality_bar=harness.quality_bar,
        evidence_ladder=harness.evidence_ladder,
        wrapper_actions=harness.wrapper_actions,
        overclaim_guards=harness.overclaim_guards,
    )


def declared_primary_harness(name: str) -> str:
    """The harness the catalog declares for this skill, or "" when it declares none.

    `primary_harness_for_skill` answers a different question and answers it for
    every name, because routing, validation, and the structure lint all need a
    harness that resolves. This one answers whether the catalog ever chose, so
    a caller that would otherwise put the fallback into authored text can say
    nothing instead. Rendered skill bodies are the caller that must use this:
    the fallback wrote `coding-handling` into the always-loaded body of skills
    that do no coding (#1690).
    """
    return _PRIMARY_HARNESSES.get(name, "")


# The fallback is the ROUTING default, not a claim about the skill. It exists
# because `_lint_harness_resolves` and `validate_skill_definition` both require
# a harness that resolves to a definition, and because a route payload's
# `selected_harness` is a required string. Never use it to author text a model
# reads as instruction; use `declared_primary_harness` there.
def primary_harness_for_skill(name: str) -> str:
    return _PRIMARY_HARNESSES.get(name, "coding-handling")


def decision_frontier_policy() -> dict[str, object]:
    return {
        "schema_version": DECISION_FRONTIER_POLICY_SCHEMA_VERSION,
        "harness": DECISION_FRONTIER_HARNESS,
        "max_rounds": DEEP_INTERVIEW_MAX_ROUNDS,
        "soft_check_round": DEEP_INTERVIEW_SOFT_CHECK_ROUND,
        "budget_scope": DECISION_FRONTIER_BUDGET_SCOPE,
        "round_unit": DECISION_FRONTIER_ROUND_UNIT,
        "decision_id_prefix": DECISION_FRONTIER_DECISION_ID_PREFIX,
        "decision_states": list(DECISION_FRONTIER_DECISION_STATES),
        "stop_rule_order": list(DECISION_FRONTIER_STOP_RULE_ORDER),
        "partial_answer_policy": DECISION_FRONTIER_PARTIAL_ANSWER_POLICY,
        "omitted_answer_transition": DECISION_FRONTIER_OMITTED_ANSWER_TRANSITION,
        "recommendation_policy": DECISION_FRONTIER_RECOMMENDATION_POLICY,
        "user_stop_scope": DECISION_FRONTIER_USER_STOP_SCOPE,
        "compaction_failure_action": DECISION_FRONTIER_COMPACTION_FAILURE_ACTION,
        "consent_gates": list(DECISION_FRONTIER_CONSENT_GATES),
    }


def coding_intent_for_skill(name: str) -> str:
    return _CODING_INTENT_BY_SKILL.get(name, "coding")


def coding_skills_for_intent(intent: str) -> tuple[str, ...]:
    return _coding_skills_by_intent().get(intent, ())


@lru_cache(maxsize=1)
def _coding_skills_by_intent() -> dict[str, tuple[str, ...]]:
    return {
        intent: tuple(
            name
            for name, mapped_intent in _CODING_INTENT_BY_SKILL.items()
            if mapped_intent == intent
        )
        for intent in CODING_INTENTS
    }


def coding_terms_for_intent(intent: str) -> tuple[str, ...]:
    return CODING_INTENT_TERMS.get(intent, ())


def retained_delegation_skill_names() -> tuple[str, ...]:
    return _retained_delegation_skill_names_cached()


@lru_cache(maxsize=1)
def _retained_delegation_skill_names_cached() -> tuple[str, ...]:
    return tuple(
        definition.name
        for definition in _builtin_definitions_cached()
        if definition.delegation_boundary in {"retained", "retained-catalog-intent"}
    )


def catalog_intent_delegation_skill_names() -> tuple[str, ...]:
    return _catalog_intent_delegation_skill_names_cached()


@lru_cache(maxsize=1)
def _catalog_intent_delegation_skill_names_cached() -> tuple[str, ...]:
    return tuple(
        definition.name
        for definition in _builtin_definitions_cached()
        if definition.delegation_boundary == "retained-catalog-intent"
    )


MEMORY_CONTEXT_POLICIES = ("compact", "explicit")
_EXPLICIT_MEMORY_CONTEXT_SKILLS = (
    "loop",
    "ultrawork",
    "idea-to-deploy",
    "cto-loop",
    "deploy-and-monitor",
    "ultraqa",
    "plan",
    "ralplan",
    "code-review",
    "ai-slop-cleaner",
    "ultraperf",
    "ask",
)


def memory_context_policy_for_skill(name: str) -> str:
    return "explicit" if name in _EXPLICIT_MEMORY_CONTEXT_SKILLS else "compact"


def explicit_memory_context_skill_names() -> tuple[str, ...]:
    return _EXPLICIT_MEMORY_CONTEXT_SKILLS


# The doctor health floor: skills OMH needs on disk to describe, diagnose, manage,
# and stop itself. This is intentionally small and independent of
# `installable_skill_names()` (the full catalog) so a health check does not force
# every packaged skill onto disk just to pass `omh doctor`.
CORE_SKILLS = (
    "oh-my-hermes",
    "doctor",
    "skill",
    "cancel",
    "agent-ops-review",
)

# The default install profile: the doctor health floor above, plus the workflow
# skills a messenger-first user needs for the chat/plan/status/handoff flows that
# make up a first session (planning with a coding handoff, gateway status-update
# and delivery policy for chat channels, executor runtime readiness before a
# handoff, and an ops observability card for status questions). Everything else
# in the catalog is opt-in via a `full` install so a default install does not add
# every packaged skill's context weight to every turn.
CORE_PROFILE_SKILLS = tuple(
    dict.fromkeys(
        CORE_SKILLS
        + (
            "plan",
            "gateway-intent-card",
            "buzz",
            "executor-runtime-readiness",
            "ops-observability-card",
        )
    )
)
DESCRIPTIONS = {definition.name: definition.description for definition in _DEFINITIONS}
