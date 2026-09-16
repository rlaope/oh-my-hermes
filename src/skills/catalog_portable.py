"""Reviewed portability policy for the Agent Skills projection.

Keys are installed display names; canonical names are accepted by the accessor.
Unlisted skills fail closed. Evidence below is from catalog definition fields,
not generated-file searches. Schemas in prose are output contracts, not RPC tools.
"""
from __future__ import annotations

from .catalog import installable_skill_definitions, omh_skill_display_name

PORTABILITY_PORTABLE = "portable"
PORTABILITY_REQUIRES_OMH_CLI = "requires-omh-cli"
PORTABILITY_HERMES_ONLY = "hermes-only"

_PORTABILITY: dict[str, str] = {
    # required_inputs require Hermes skill discovery; final_checklist owns wrapper routing.
    'omh-routing': PORTABILITY_HERMES_ONLY,
    # required_inputs use leading /omh wrapper intake and live full-catalog routing, not host skill nomination.
    'omh-meta-router': PORTABILITY_HERMES_ONLY,
    # Catalog reference/retired surface, not an installable workflow; no Agent Skills projection in v1.
    'ulw-ralph': PORTABILITY_HERMES_ONLY,
    # Catalog reference/retired surface, not an installable workflow; no Agent Skills projection in v1.
    'ulw-goal': PORTABILITY_HERMES_ONLY,
    # expected_outputs include loop_cycle/v2 and loop_status_card; commands.loop -> create_loop_cycle uses local files, no runtime; native goal controls excluded by override.
    'ulw-loop': PORTABILITY_REQUIRES_OMH_CLI,
    # Catalog reference/retired surface, not an installable workflow; no Agent Skills projection in v1.
    'ulw-process': PORTABILITY_HERMES_ONLY,
    # expected_outputs stage reviewed domain-intelligence candidates; optional source lookup itself is read-only.
    'ulw-context': PORTABILITY_REQUIRES_OMH_CLI,
    # required_inputs: initial request; expected_outputs: clarified brief; final_checklist requires evidence/approval, not a native runtime.
    'ulw-interview': PORTABILITY_PORTABLE,
    # required_inputs: reviewed context; expected_outputs: confirmed target statement: Learn X now so I can do/decide Y in context Z by T.; final_checklist requires evidence/approval, not a native runtime.
    'omh-jit-learn': PORTABILITY_PORTABLE,
    # Catalog reference/retired surface, not an installable workflow; no Agent Skills projection in v1.
    'ulw-team': PORTABILITY_HERMES_ONLY,
    # accepted plan and lane scopes are neutral; retained handoff-risk-scan/goal ledger commands require CLI, native RPC steps overridden.
    'ulw-work': PORTABILITY_REQUIRES_OMH_CLI,
    # why_this_exists and final_checklist require the explicit Hermes/external-owner lane boundary.
    'ulw-maestro': PORTABILITY_HERMES_ONLY,
    # required_inputs: research question; expected_outputs: source-backed synthesis; final_checklist requires evidence/approval, not a native runtime.
    'ulw-research': PORTABILITY_PORTABLE,
    # required_inputs: question; expected_outputs: cited answer; final_checklist requires evidence/approval, not a native runtime.
    'omh-web-research': PORTABILITY_PORTABLE,
    # why_this_exists is source-first product explanation; required_inputs select public/local scope.
    # expected_outputs are sourced answers and passive CLI/metadata facts; final_checklist and
    # handoff_policy route mutations elsewhere. No Hermes runtime is required; local CLI is.
    'omh-docs': PORTABILITY_REQUIRES_OMH_CLI,
    # required_inputs: source target or topic; expected_outputs: source_finder_plan/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-source-finder': PORTABILITY_PORTABLE,
    # required_inputs: business question; expected_outputs: evidence table; final_checklist requires evidence/approval, not a native runtime.
    'omh-research-brief': PORTABILITY_PORTABLE,
    # why_this_exists composes Hermes profiles, cron, knowledge storage, and delivery glue.
    'omh-research-department': PORTABILITY_HERMES_ONLY,
    # required_inputs: paper identity or attachment reference; expected_outputs: paper_learning_card/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-paper-learning': PORTABILITY_PORTABLE,
    # required_inputs: goal; expected_outputs: options; final_checklist requires evidence/approval, not a native runtime.
    'omh-decide': PORTABILITY_PORTABLE,
    # required_inputs: meeting goal; expected_outputs: agenda; final_checklist requires evidence/approval, not a native runtime.
    'omh-meeting-brief': PORTABILITY_PORTABLE,
    # required_inputs: feedback items or summary; expected_outputs: clusters; final_checklist requires evidence/approval, not a native runtime.
    'omh-feedback-triage': PORTABILITY_PORTABLE,
    # required_inputs: period; expected_outputs: finance_scope_source_record/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-finance-analysis': PORTABILITY_PORTABLE,
    # required_inputs: role or people-process outcome; expected_outputs: role/outcome and must-have versus trainable-criteria brief; final_checklist requires evidence/approval, not a native runtime.
    'omh-people-ops': PORTABILITY_PORTABLE,
    # required_inputs: jurisdiction; expected_outputs: legal_scope_authority_record/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-legal-compliance-review': PORTABILITY_PORTABLE,
    # required_inputs: support case; expected_outputs: customer-safe reply draft with stated facts, unknowns, and tone; final_checklist requires evidence/approval, not a native runtime.
    'omh-support-operations': PORTABILITY_PORTABLE,
    # required_inputs: learners; expected_outputs: curriculum_learner_outcome_brief/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-curriculum-design': PORTABILITY_PORTABLE,
    # required_inputs: locale; expected_outputs: locale/audience/context and source-version brief; final_checklist requires evidence/approval, not a native runtime.
    'omh-localization-review': PORTABILITY_PORTABLE,
    # required_inputs: account or segment; expected_outputs: sales_opportunity_evidence_record/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-sales-development': PORTABILITY_PORTABLE,
    # required_inputs: product evidence; expected_outputs: problem, user, evidence, metric, goal, and non-goal brief; final_checklist requires evidence/approval, not a native runtime.
    'omh-product-brief': PORTABILITY_PORTABLE,
    # required_inputs: status evidence; expected_outputs: status summary; final_checklist requires evidence/approval, not a native runtime.
    'omh-ops-review': PORTABILITY_PORTABLE,
    # required_inputs: cadence or meeting type; expected_outputs: operation artifact; final_checklist requires evidence/approval, not a native runtime.
    'omh-operating-rhythm': PORTABILITY_PORTABLE,
    # required_inputs: audience; expected_outputs: report package; final_checklist requires evidence/approval, not a native runtime.
    'omh-report-package': PORTABILITY_PORTABLE,
    # required_inputs: audience or recipient; expected_outputs: material_artifact/v1 plan; final_checklist requires evidence/approval, not a native runtime.
    'omh-materials-package': PORTABILITY_PORTABLE,
    # required_inputs: source/image; expected_outputs: visual_prompt_card/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-image-cards': PORTABILITY_PORTABLE,
    # required_inputs: mode: design, review, or improve; expected_outputs: apple_design_brief/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-apple-design': PORTABILITY_PORTABLE,
    # required_inputs: bounded target surface, audience, and primary task; expected_outputs: design_orchestration/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-design-orchestration': PORTABILITY_PORTABLE,
    # required_inputs: surface/channel; expected_outputs: design_quality_gate/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-design-quality-gate': PORTABILITY_PORTABLE,
    # required_inputs: the target URL, route, or rendered capture being judged; expected_outputs: award_bar_score/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-award-bar-score': PORTABILITY_PORTABLE,
    # required_inputs are UI evidence; quality_bar requires offline omh design data before token selection.
    'omh-frontend': PORTABILITY_REQUIRES_OMH_CLI,
    # required_inputs: the target files or component, and the framework in use; expected_outputs: preview change plan with per-change line refs, before/after, safety reason, and category counts; final_checklist requires evidence/approval, not a native runtime.
    'omh-frontend-refactor': PORTABILITY_PORTABLE,
    # required_inputs: the service, endpoint, or data surface being changed; expected_outputs: backend_service_contract/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-backend': PORTABILITY_PORTABLE,
    # required_inputs: the crate, module, or function being changed; expected_outputs: rust_change_contract/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-rust': PORTABILITY_PORTABLE,
    # required_inputs: the binary, crash signature, or fault symptom; expected_outputs: native_fault_statement/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-native-debugging': PORTABILITY_PORTABLE,
    # required_inputs: target app, page, route, component, or design system; expected_outputs: accessibility_audit_plan/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-accessibility-audit': PORTABILITY_PORTABLE,
    # expected_outputs are evidence gates; artifact_expectations import host receipts through omh web-qa observation.
    'omh-visual-qa': PORTABILITY_REQUIRES_OMH_CLI,
    # required_inputs: failing command, CI job, PR check, or tool name; expected_outputs: build_failure_triage_plan/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-build-failure-triage': PORTABILITY_PORTABLE,
    # required_inputs: workspace or repo root; expected_outputs: workspace_audit_plan/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-workspace-audit': PORTABILITY_PORTABLE,
    # required_inputs: product, service, release, or artifact scope; expected_outputs: production_audit_plan/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-production-audit': PORTABILITY_PORTABLE,
    # required_inputs: claim or change under verification; expected_outputs: verification_gate_plan/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-verification-gate': PORTABILITY_PORTABLE,
    # expected_outputs require paired_run_decision; safety_rules require signed Hermes-child dispatch receipts.
    'omh-agent-evaluation': PORTABILITY_HERMES_ONLY,
    # required_inputs: source corpus: skills, prompts, traces, reviews, failures, or docs; expected_outputs: rules_distillation_plan/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-rules-distill': PORTABILITY_PORTABLE,
    # required_inputs: repo root or supplied source context; expected_outputs: codebase_onboarding_plan/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-codebase-onboarding': PORTABILITY_PORTABLE,
    # expected_outputs require codegraph command plans and observed omh codegraph artifacts.
    'omh-codegraph-refresh': PORTABILITY_REQUIRES_OMH_CLI,
    # expected_outputs explicitly require omh codegraph uml source and render plan.
    'omh-codebase-uml': PORTABILITY_REQUIRES_OMH_CLI,
    # expected_outputs require context_budget_plan; CLI prepares local route-capacity metadata, no host hook is ported.
    'omh-context-budget-review': PORTABILITY_REQUIRES_OMH_CLI,
    # required_inputs: target workflow, code change, prompt, tool, dependency, or release surface; expected_outputs: security_safety_review_plan/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-security-safety-review': PORTABILITY_PORTABLE,
    # required_inputs: components, data flows, known trust boundaries, deployed controls, threat actors in scope; expected_outputs: application_threat_model/v1; the whole workflow is analysis over supplied architecture with no OMH CLI call and no Hermes-only tool.
    'omh-application-threat-model': PORTABILITY_PORTABLE,
    # expected_outputs require hermes_ops_blueprint and hermes_recurring_intent lifecycle records.
    'omh-automation-blueprint': PORTABILITY_HERMES_ONLY,
    # required_inputs: what is broken now, blast radius, available responders, the recovery signal; expected_outputs: live_incident_record/v1; the workflow is judgement over supplied facts, and every external effect is already delegated to connector-operator.
    'omh-live-incident-response': PORTABILITY_PORTABLE,
    # required_inputs: service or incident scope; expected_outputs: reliability review; final_checklist requires evidence/approval, not a native runtime.
    'omh-reliability-review': PORTABILITY_PORTABLE,
    # required_inputs: product idea; expected_outputs: stage rail; final_checklist requires evidence/approval, not a native runtime.
    'omh-idea-to-deploy': PORTABILITY_PORTABLE,
    # required_inputs: the feature the model is supposed to perform; expected_outputs: rail decisions across provider boundary, structured output, prompt artifacts, retrieval grounding, evaluation; final_checklist requires evidence/approval, not a native runtime.
    'omh-llm-app-dev': PORTABILITY_PORTABLE,
    # required_inputs: operating signals; expected_outputs: priority frame; final_checklist requires evidence/approval, not a native runtime.
    'omh-cto-loop': PORTABILITY_PORTABLE,
    # required_inputs: release scope; expected_outputs: pre-deploy checklist; final_checklist requires evidence/approval, not a native runtime.
    'omh-deploy-and-monitor': PORTABILITY_PORTABLE,
    # required_inputs: changed behavior; expected_outputs: adversarial scenarios; final_checklist requires evidence/approval, not a native runtime.
    'ulw-qa': PORTABILITY_PORTABLE,
    # required_inputs: requirements; expected_outputs: plan; final_checklist requires evidence/approval, not a native runtime.
    'omh-plan': PORTABILITY_PORTABLE,
    # required_inputs: requirements; expected_outputs: reviewed plan; final_checklist requires evidence/approval, not a native runtime.
    'ulw-plan': PORTABILITY_PORTABLE,
    # required_inputs: the proposal, plan draft, or direction under review; expected_outputs: per-perspective independent findings; final_checklist requires evidence/approval, not a native runtime.
    'omh-adversarial-consensus': PORTABILITY_PORTABLE,
    # required_inputs: diff or files; expected_outputs: ranked findings per axis; final_checklist requires evidence/approval, not a native runtime.
    'omh-code-review': PORTABILITY_PORTABLE,
    # required_inputs: target smell, or a scoped file list when the user has not named one; expected_outputs: smell inventory naming each finding's category before any edit; final_checklist requires evidence/approval, not a native runtime.
    'omh-ai-slop-cleaner': PORTABILITY_PORTABLE,
    # required_inputs: the decided target shape (what moves where), or a pointer to the accepted plan that decided it; expected_outputs: reconnaissance: affected files, ownership boundaries, hidden coupling, blast radius; final_checklist requires evidence/approval, not a native runtime.
    'omh-refactor-plan': PORTABILITY_PORTABLE,
    # required_inputs: the repo root or the scoped path list the audit is confined to; expected_outputs: orientation summary: manifests read, churn ranking, largest files, test and CI entry points; final_checklist requires evidence/approval, not a native runtime.
    'omh-tech-debt-audit': PORTABILITY_PORTABLE,
    # required_inputs: chosen technology; expected_outputs: source-backed guidance; final_checklist requires evidence/approval, not a native runtime.
    'omh-best-practice-research': PORTABILITY_PORTABLE,
    # required_inputs: research objective; expected_outputs: research artifact; final_checklist requires evidence/approval, not a native runtime.
    'omh-autoresearch-goal': PORTABILITY_PORTABLE,
    # required_inputs: metric; expected_outputs: measurement delta; final_checklist requires evidence/approval, not a native runtime.
    'omh-performance-goal': PORTABILITY_PORTABLE,
    # required_inputs: the model id(s) and where the weights live (HF id, local path, gated or not); expected_outputs: engine and quantization verdict from the decision tables, with the rejected options named; final_checklist requires evidence/approval, not a native runtime.
    'omh-inference-serving': PORTABILITY_PORTABLE,
    # required_inputs require router recognition; quality_bar mutates Hermes/Maestro model routing.
    'omh-model-optimization': PORTABILITY_HERMES_ONLY,
    # required_inputs: symptom or suspected slow surface; expected_outputs: baseline record; final_checklist requires evidence/approval, not a native runtime.
    'ulw-perf': PORTABILITY_PORTABLE,
    # required_inputs: audience scale (personal, small group, team, or organization); expected_outputs: wiki_blueprint/v1 with organization model, rationale, breaking conditions, and one alternative; final_checklist requires evidence/approval, not a native runtime.
    'omh-wiki': PORTABILITY_PORTABLE,
    # required_inputs: question; expected_outputs: advisor summary; final_checklist requires evidence/approval, not a native runtime.
    'omh-ask': PORTABILITY_PORTABLE,
    # required_inputs name active workflow state; expected_outputs clear local OMH state, not a host process.
    'omh-cancel': PORTABILITY_REQUIRES_OMH_CLI,
    # expected_outputs mutate the managed Hermes skill inventory; final_checklist inspects managed config paths.
    'omh-skill': PORTABILITY_HERMES_ONLY,
    # required_inputs require Hermes home; final_checklist verifies plugin and Hermes registration.
    'omh-doctor': PORTABILITY_HERMES_ONLY,
    # expected_outputs remove/retain managed Hermes skills and reverse capability policy.
    'omh-capability-toggle': PORTABILITY_HERMES_ONLY,
    # required_inputs are local coding artifacts; expected_outputs read per-unit runtime/model and observed accounting.
    'omh-running-work-board': PORTABILITY_REQUIRES_OMH_CLI,
    # expected_outputs configure native role aliases/providers or Maestro recommendations.
    'omh-model-setup': PORTABILITY_HERMES_ONLY,
    # required_inputs require installed Hermes version and native parallel-tool capability.
    'omh-parallel-tools': PORTABILITY_HERMES_ONLY,
    # required_inputs target auxiliary web-extract slots; expected_outputs edit Hermes env/routing.
    'omh-websearch-setup': PORTABILITY_HERMES_ONLY,
    # expected_outputs include MCP configuration writes under the Hermes setup harness.
    'omh-morning-brief': PORTABILITY_HERMES_ONLY,
    # Catalog reference/retired surface, not an installable workflow; no Agent Skills projection in v1.
    'omh-quality-evidence-loop': PORTABILITY_HERMES_ONLY,
    # required_inputs require Hermes home or an active Buzz conversation; transport ownership is Hermes.
    'omh-buzz': PORTABILITY_HERMES_ONLY,
    # required_inputs: public report or summary; expected_outputs: github_issue_intake/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-github-issue-intake': PORTABILITY_PORTABLE,
    # required_inputs: decision question; expected_outputs: decision_prototype/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-decision-prototype': PORTABILITY_PORTABLE,
    # required_inputs: lifecycle objective and stage; expected_outputs: lifecycle_growth_brief/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-lifecycle-growth': PORTABILITY_PORTABLE,
    # required_inputs: problem hypothesis; expected_outputs: discovery_decision_frame/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-product-discovery-validation': PORTABILITY_PORTABLE,
    # required_inputs: pipeline snapshot; expected_outputs: sales_pipeline_scope/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-sales-pipeline-review': PORTABILITY_PORTABLE,
    # required_inputs: user request; expected_outputs: github-event-ops/v1 card or guidance; final_checklist requires evidence/approval, not a native runtime.
    'omh-github-event-ops': PORTABILITY_PORTABLE,
    # expected_outputs require omh_agent_board RPC; final_checklist invokes Hermes native_action.
    'omh-agent-board': PORTABILITY_HERMES_ONLY,
    # expected_outputs are review-first local memory candidates; native-memory guidance is excluded by override.
    'omh-memory-new': PORTABILITY_REQUIRES_OMH_CLI,
    # use_when reviews Hermes USER.md/MEMORY.md; expected_outputs are native write guidance.
    'omh-memory-sync': PORTABILITY_HERMES_ONLY,
    # final_checklist binds platform/thread delivery and wrapper actions, not a host-neutral workflow.
    'omh-gateway-intent-card': PORTABILITY_HERMES_ONLY,
    # final_checklist requires hermes_coding_harness lane evidence; readiness is Maestro/harness routing.
    'omh-executor-runtime-readiness': PORTABILITY_HERMES_ONLY,
    # required_inputs: user request; expected_outputs: deliverable-package/v1 card or guidance; final_checklist requires evidence/approval, not a native runtime.
    'omh-deliverable-package': PORTABILITY_PORTABLE,
    # required_inputs: user request; expected_outputs: voice-operator/v1 card or guidance; final_checklist requires evidence/approval, not a native runtime.
    'omh-voice-input': PORTABILITY_PORTABLE,
    # final_checklist requires omh_browser admission and native browser blocking; host plugin boundary.
    'omh-browser': PORTABILITY_HERMES_ONLY,
    # required_inputs: user request; expected_outputs: workspace_file_task_card/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-files': PORTABILITY_PORTABLE,
    # required_inputs: user request; expected_outputs: command_task_card/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-terminal': PORTABILITY_PORTABLE,
    # required_inputs: user request; expected_outputs: connector_task_card/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-apps': PORTABILITY_PORTABLE,
    # required_inputs: user request; expected_outputs: live_info_task_card/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-live-info': PORTABILITY_PORTABLE,
    # required_inputs: user request; expected_outputs: external_connector_readiness_card/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-external-connector-readiness': PORTABILITY_PORTABLE,
    # use_when and artifact_expectations target Hermes slash-command registration and collisions.
    'omh-prompt-import-readiness': PORTABILITY_HERMES_ONLY,
    # required_inputs: user request; expected_outputs: physical_device_readiness_card/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-physical-device-readiness': PORTABILITY_PORTABLE,
    # required_inputs: user request; expected_outputs: content_task_card/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-content-operator': PORTABILITY_PORTABLE,
    # required_inputs: user request; expected_outputs: media_input_task_card/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-media-input': PORTABILITY_PORTABLE,
    # required_inputs: user request; expected_outputs: data_analysis_task_card/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-data-analysis': PORTABILITY_PORTABLE,
    # required_inputs: user request; expected_outputs: toolbelt-readiness/v1 card or guidance; final_checklist requires evidence/approval, not a native runtime.
    'omh-toolbelt-readiness': PORTABILITY_PORTABLE,
    # required_inputs: user request; expected_outputs: harness_session_inventory/v1 card or guidance; final_checklist requires evidence/approval, not a native runtime.
    'omh-harness-session-inventory': PORTABILITY_PORTABLE,
    # required_inputs: user request; expected_outputs: ops-observability-card/v1 card or guidance; final_checklist requires evidence/approval, not a native runtime.
    'omh-ops-observability-card': PORTABILITY_PORTABLE,
    # expected_outputs read hermes_achievements_observation from native plugin artifacts.
    'omh-achievements': PORTABILITY_HERMES_ONLY,
    # required_inputs: user request; expected_outputs: agent-ops-review/v1 card or guidance; final_checklist requires evidence/approval, not a native runtime.
    'omh-agent-ops-review': PORTABILITY_PORTABLE,
    # required_inputs: user request; expected_outputs: agent_debug_report/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-agent-debug': PORTABILITY_PORTABLE,
    # required_inputs: user request; expected_outputs: failure_signal_audit_plan/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-failure-signal-audit': PORTABILITY_PORTABLE,
    # required_inputs: user request; expected_outputs: instinct_ledger_plan/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-instinct-ledger': PORTABILITY_PORTABLE,
    # required_inputs: user request; expected_outputs: skill_scout_query/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-skill-scout': PORTABILITY_PORTABLE,
    # expected_outputs inspect catalog/generated/reference/harness status via local OMH catalog, not host loading.
    'omh-skill-health': PORTABILITY_REQUIRES_OMH_CLI,
    # artifact_expectations require browser promotion approval and native managed-skill visibility.
    'omh-workflow-learning': PORTABILITY_HERMES_ONLY,
    # expected_outputs query reviewed rejected-decision records; final_checklist excludes expired candidates.
    'omh-decision-recall': PORTABILITY_REQUIRES_OMH_CLI,
    # expected_outputs read run_efficiency_report from local run context and supplied observations.
    'omh-run-efficiency': PORTABILITY_REQUIRES_OMH_CLI,
    # required_inputs: user request; expected_outputs: provider_profile_posture/v1; final_checklist requires evidence/approval, not a native runtime.
    'omh-provider-profile-posture': PORTABILITY_PORTABLE,
}


def skill_portability(name: str) -> str:
    """Return the reviewed class, failing closed for unknown names."""
    key = name if name in _PORTABILITY else omh_skill_display_name(name)
    return _PORTABILITY.get(key, PORTABILITY_HERMES_ONLY)


def portable_skill_names() -> tuple[str, ...]:
    """Installed display names in catalog order, not alphabetical order."""
    return tuple(
        omh_skill_display_name(definition.name)
        for definition in installable_skill_definitions()
        if skill_portability(definition.name) != PORTABILITY_HERMES_ONLY
    )


# Complete replacement lines for only the fields whose host boundary changes.
# Hermes rendering never reads this mapping. Scalar prose fields use one line.
PORTABLE_OVERRIDES: dict[str, dict[str, tuple[str, ...]]] = {'ulw-plan': {'artifact_expectations': ('Record the plan as a durable file/ledger the host can resume, with '
                                        'goals, options, risks, acceptance criteria, and exact verification '
                                        'commands.',
                                        'Record the user acceptance against that exact artifact; acceptance '
                                        'is not permission to start implementation.'),
              'safety_rules': ('Do not implement directly from the planning lane.',
                               'Do not invent codebase or web evidence; label missing evidence and source '
                               'gaps.',
                               'Make acceptance criteria testable.',
                               'Record unresolved tradeoffs explicitly.',
                               'Keep rejected options and handoff readiness separate from accepted execution '
                               'evidence.',
                               'Write plans only to an explicitly chosen repository or host-owned planning '
                               "path; never write another product's state root."),
              'opening_steps': ('Use the host task list or a durable checklist for repo facts, evidence '
                                'gaps, options, risks, verification, and plan acceptance; keep one item '
                                'active and insert research when evidence is missing. Checklist states are '
                                'declarations, not execution evidence.',),
              'quality_bar': ('Start from observed repo facts and source/web evidence when freshness or '
                              'external behavior matters.',
                              'Include planner view, critic/risk review, alternative paths, rejected '
                              'options, and a testability check before handoff.',
                              'Produce testable acceptance criteria and exact verification commands or '
                              'explain why they are not yet knowable.',
                              'Record unresolved tradeoffs and evidence gaps instead of flattening '
                              'uncertainty.',
                              'When plan-shaping evidence is missing — current external behavior, contested '
                              'claims, or unstudied reference implementations — run the `research` workflow '
                              'as a bounded in-plan stage (not an exhaustive deep-research run) before '
                              'comparing options, record its dossier the way the `research` artifact '
                              'contract requires, and consume it instead of planning on assumptions.',
                              'Consume a recorded `research` dossier when one exists: plan options and '
                              'rejected alternatives should cite its decision drivers and verified claims.',
                              'End with a selected executor/runtime handoff shape only after the plan is '
                              'accepted.',
                              'Plan acceptance approves the plan content, not execution: after acceptance, '
                              "recommend the follow-on path that fits the work's shape — `ultrawork` durable "
                              'checkpoints for progress that must survive sessions as a checkpointed ledger, '
                              '`ultrawork` coordinated lanes for an accepted plan split into disjoint '
                              'parallel lanes, `ultrawork` single-owner persistence for one already-scoped '
                              'task with a single owner, `ultrawork` for one bounded delivery cycle, or a '
                              'direct selected executor/runtime handoff for a single prepared coding change '
                              "— state the fit reason in one line, and start it only after the user's "
                              'explicit go-ahead.',
                              'Do not implement directly from consensus planning.'),
              'why_this_exists': ('`ralplan` exists to make planning reviewable before execution: the host '
                                  'should gather codebase/source facts, compare options, expose risks, '
                                  'define acceptance criteria, and prepare a handoff without pretending '
                                  'implementation already happened.',)},
 'ulw-work': {'quality_bar': ("Do not start this engine as an automatic continuation of another skill's "
                              'output: an accepted plan, a clarified brief, or a routing recommendation is '
                              'planning evidence, not permission. Unless the user explicitly invoked this '
                              'engine themselves, restate in one line what will start (engine, scope, '
                              "selected executor) and wait for the user's explicit go-ahead first.",
                              'Resolve the dependency_topology decision before any dispatch: work coupled by '
                              'a shared invariant or inseparable edit boundary collapses to one owner; '
                              'separable but ordered units get explicit acyclic dependency edges; '
                              'independent units form the dependency-ready parallel frontier; no unit '
                              'dispatches without scope, acceptance criteria, a verification command, and an '
                              'owner route - load `references/dependency-topology.md` for the full '
                              'discipline.',
                              'Attach acceptance criteria, verification commands, and review expectations to '
                              'each lane.',
                              'Keep dispatch, execution, review, CI, and merge status evidence separate.',
                              'After final brief composition and before unattended coding handoff, '
                              'explicitly run `omh handoff-risk-scan --brief-file <final-brief> --repo '
                              '<workspace> --strict --json`. Route high_risk (exit 1) to existing '
                              'confirmation or security-safety-review; scan_error (exit 2) requires repaired '
                              'input and a new scan. Clear never grants permission or bypasses metadata '
                              'preflight, approval, or host policy.',
                              'Write every lane or node prompt standalone with TASK, DELIVERABLE, SCOPE, '
                              'VERIFY, and STOP WHEN in that order, exact paths and binary pass/fail '
                              'observables, and one role per node; a dependency edge orders execution only '
                              'and never substitutes upstream output.',
                              'End every code-changing run with a verification fan-in that depends on all '
                              "producer lanes, runs the repository's real test/build command, and reports "
                              'captured binary pass/fail output; downstream consumers re-check upstream '
                              'claims before trusting them.',
                              'For each behavioral increment follow PIN -> RED -> GREEN -> SURFACE -> CLEAN: '
                              'pin behavior a refactor could hide, capture the intended failing proof before '
                              'implementation, make the smallest change, exercise the real user surface, and '
                              'tear down every QA resource with a cleanup receipt; tests alone never prove '
                              'completion.',
                              'Keep one inspectable, append-only evidence ledger for the run using the '
                              'available goal/runtime records: record the tier decision, dependency '
                              'topology, todo transitions, command outputs, real-surface artifacts, and '
                              'cleanup receipts when each occurs.',
                              "For tests-first work, capture the new test's failing nonzero output before "
                              'implementation and its passing zero output plus the full suite before done; '
                              'never edit, delete, skip, or weaken a test to make it pass.',
                              '[capability:coordinated_scope] Keep the current host as coordinator and '
                              "narrator; delegate through the host's own subagent/task mechanism with "
                              'explicit ownership, or run lanes sequentially when unavailable.',
                              '[capability:delivery_boundary] Complete exactly one plan-to-PR delivery '
                              'cycle, then stop with status, evidence gaps, or a next recommended workflow.',
                              '[capability:delivery_boundary] Start a delivery cycle with codebase/source '
                              'research and a ralplan-style decision record before implementation handoff.',
                              '[capability:delivery_boundary] Run code-review as a gate after implementation '
                              'evidence exists; review preparation alone is not review evidence.',
                              '[capability:delivery_boundary] End a delivery cycle with a PR-ready or '
                              'PR-observed report that separates prepared, executed, reviewed, verified, CI, '
                              'and PR evidence.',
                              "[capability:delivery_boundary] Use the host's own subagent/task mechanism "
                              'with explicit owner, acceptance criteria, verification commands, and a '
                              'resumable ledger for durable checkpoints. Never imply hidden execution.',
                              "When the user explicitly selects an external coding owner, use the host's "
                              'authorized task mechanism, verify its actual capabilities, and capture its '
                              'session/task handle. Missing delegation means sequential work or a named '
                              'blocker, never fabricated dispatch.',
                              'Name each lane owner and its actual host capabilities before dispatch; do not '
                              'infer model or tool routing from inheritance.',
                              'Choose the wait strategy before starting long-running work and bind it to a '
                              'completion signal the host exposes, never to a status loop: a command that '
                              'fits one tool call runs once in the foreground with a duration-sized timeout; '
                              'a longer terminal command runs in the background with completion notification '
                              'armed and no process-status polling; a delegated lane relies on its delivered '
                              'result while the parent continues independent work or ends the turn; a CI, '
                              'PR, deploy, file, port, log-line, or external-session condition uses the '
                              "host's monitor when observed, else exactly ONE bounded watcher or adaptive "
                              'backoff outside model turns. Record the handle and observation mode at '
                              'dispatch; every armed wait needs a hard deadline, a cancellation path, and a '
                              'fallback naming the missing capability. Each wait closes in one terminal '
                              'state with bounded evidence; an unbounded idle or busy-wait is a defect and a '
                              'lost notification times out. One decision-changing midpoint peek and any '
                              'user-requested status check stay allowed; neither is the wait mechanism. '
                              'Ladder and terminal states: shared rail.',
                              'A mid-run user message is an interjection, not a stop: answer it briefly and, '
                              'in the same reply, continue the run — re-read the phase todo when one is '
                              'active and dispatch or advance the next pending step, or name the armed wait '
                              'it is waiting on -- handle, bound completion signal, deadline -- instead of '
                              "re-reading status. Only the user's explicit stop or cancel, or the engine's "
                              'own completion gate, ends the run; when the interjection changes scope, say '
                              'so and update the declared plan or todo instead of silently abandoning it. A '
                              'mid-run message is the latest steering for the active task, not automatically '
                              'a replacement objective: it replaces the objective when the user says so and '
                              'steers the current one otherwise.',
                              'A follow-up that needs new authority, materially expands the scope, or '
                              'changes external state not already authorized is described first and started '
                              "only on the user's approval; persistence never broadens the authorized scope. "
                              'A refused escalation gets a safer alternative inside the boundary, or the '
                              'authorization the boundary asks for — never a workaround or an indirect '
                              'execution.',
                              'The closing brief scales to the change: one or two sentences plus the '
                              'observed validation for a simple change, more only when the complexity earns '
                              'it. Lead with the result or decision; omit abandoned approaches unless they '
                              'explain a tradeoff the reader needs; narrate no internal bookkeeping (todo '
                              'transitions, follow-up declarations, waits). Required closing lines stay '
                              'outside this scaling: the observed run summary, and any prepared-not-observed '
                              "or unmerged work, are stated whatever the brief's length.",
                              'Close with observed host accounting when available, or explicitly report '
                              'run-summary not_available. Never estimate token counts, elapsed time, or '
                              'models used.',
                              '[capability:single_owner_persistence] Do not enter a finish-until-done loop '
                              'until scope, acceptance criteria, and verification commands are concrete.',
                              '[capability:single_owner_persistence] For single-owner coding edits, prepare '
                              'and track the selected runtime path instead of implying unobserved work '
                              'happened or hiding execution inside chat narration.',
                              '[capability:single_owner_persistence] Report single-owner completion only '
                              'from observed execution and verification evidence, with remaining risks '
                              'named.',
                              '[capability:durable_checkpoint] Keep goal state durable, inspectable, and '
                              'separate from chat narration in the metadata-only .omh/goals goal_ledger/v1.',
                              '[capability:durable_checkpoint] Checkpoint every success, blocker, and final '
                              'quality gate with fresh evidence.',
                              '[capability:durable_checkpoint] Reject completion with a summary-only '
                              'goal_completion_gate/v1 result until required criteria, blockers, and '
                              'explicitly linked runtime runs are satisfied.',
                              '[capability:durable_checkpoint] Name the one element gating goal progress '
                              "from the linked loop's loop_constraint_assessment/v1 before checkpointing the "
                              'next step; load `ulw-loop/references/goal-constraint-discipline.md` for the '
                              'method.'),
              'safety_rules': ('Do not run two concurrently runnable lanes with overlapping write scopes; a '
                               'shared file requires an ordering edge or one owner.',
                               'Keep orchestration/status and implementation ownership explicit in the '
                               'current host; preserve prepared versus observed evidence boundaries.',
                               'Record unobserved executor work as prepared_not_observed or not_observed.',
                               '[capability:coordinated_scope] Use coordination lanes only when work is '
                               'independent; if two lanes are not independent, collapse them under one owner '
                               'or re-plan before dispatch.',
                               '[capability:coordinated_scope] Keep shared-file edits under one owner; if '
                               'integration reveals a shared-file conflict, stop lane fan-out and reassign '
                               'ownership before continuing.',
                               '[capability:coordinated_scope] Record unobserved delegation as not_observed; '
                               'a delegation record exists only when separate participants are observed.',
                               '[capability:delivery_boundary] Do not continue into a repeated feedback '
                               'loop; recommend `loop` when the user wants ongoing cycles.',
                               '[capability:delivery_boundary] Do not skip planning when the delivery '
                               'request is broad, risky, or user-visible; a ralplan-style or reviewed plan '
                               'names acceptance criteria, risks, and verification commands.',
                               '[capability:delivery_boundary] Run docs sync only when behavior, setup, '
                               'commands, examples, or public claims changed.',
                               '[capability:delivery_boundary] Keep web research source-backed and '
                               'permission-aware; do not run hidden network or LLM calls from OMH core.'),
              'opening_steps': ("Initialize an English phase checklist through the host's task mechanism or "
                                'a durable file: bootstrap, each implementation/verification lane, '
                                'independent review, and evidence/cleanup close. Keep one outcome active and '
                                'update declarations from observed results.',),
              'final_checklist': ('The phase checklist was declared before engine work started and every '
                                  'outcome reached a terminal state; a run that declared none, or that left '
                                  'outcomes pending, is not complete.',
                                  'Every concurrently runnable lane is disjoint by write scope, invariant, '
                                  'or responsibility, and every ordered unit carries an explicit acyclic '
                                  'dependency edge, before parallel handoffs are prepared.',
                                  'Each lane has acceptance criteria, verification command, worker protocol '
                                  'expectation, and review owner.',
                                  "Every lane's owner and routing were named before dispatch, never inferred "
                                  'from inheritance; a lane dispatched on inherited routing is unrouted.',
                                  'Builder, verifier, reviewer, documentation, and PR lanes have explicit '
                                  'host task owners and observed evidence.',
                                  'Worker ACK, dispatch, result, review, CI, and merge evidence are observed '
                                  'or explicitly missing.',
                                  'Integration verification ran after lane results before the final status '
                                  'claims completion.',
                                  'Changed behavior was exercised through the real user surface after '
                                  'diagnostics and relevant tests passed, and every spawned QA resource has '
                                  'a cleanup receipt.',
                                  'The closing brief includes observed host accounting or an explicit '
                                  'run-summary not_available statement, never estimated usage.',
                                  '[capability:coordinated_scope] The integrated status names which '
                                  'coordination lanes are observed, blocked, or still prepared_not_observed.',
                                  '[capability:coordinated_scope] Coordination teardown is explicit: '
                                  'released lanes are named and closed instead of lingering as implicit '
                                  'owners.',
                                  '[capability:durable_checkpoint] The goal_status_card/v1 or '
                                  'goal_continuation/v1 names the next action and the final status says '
                                  'complete, blocked, or continue with the exact remaining checkpoint.',
                                  '[capability:durable_checkpoint] All explicitly linked coding milestones '
                                  'have matching observed runtime evidence or stay prepared_not_observed and '
                                  'named as gaps without closing the goal.',
                                  '[capability:durable_checkpoint] Long-running or background executor '
                                  'milestones report observed handles, current state, changed-file '
                                  'summaries, missing checks, and prepared-vs-observed boundaries while work '
                                  'is running.',
                                  '[capability:durable_checkpoint] Branch, PR, CI, review, and merge claims '
                                  'are verified against local HEAD, remote branch SHA, PR head SHA, and '
                                  'merge commit before saying a fix landed.'),
              'why_this_exists': ('`ultrawork` exists to choose one-owner, ordered-dependency, or '
                                  'independent-frontier execution for an accepted implementation plan '
                                  'without letting concurrency blur ownership, verification, worker '
                                  'protocol, worktree isolation, or observed runtime evidence. It also '
                                  'carries four named internal capabilities absorbed from sibling engines: '
                                  '`coordinated_scope` (coordinated worker lanes), `delivery_boundary` (one '
                                  'bounded plan-to-PR cycle), `single_owner_persistence` (one owner finishes '
                                  'and verifies), and `durable_checkpoint` (durable goal ledger with '
                                  'checkpoints and a final gate).',)},
 'ulw-loop': {'quality_bar': ('Treat direct `loop`, `./loop`, `$loop`, and OMH loop invocations as a '
                              'start/continue signal rather than a picker or passive clarification path.',
                              'Classify the goal as task, project, ambition, external-wait, or unclear '
                              'inside the loop, then keep progressing until a real permission, evidence, '
                              'verification, context, budget, or external-wait gate appears.',
                              'A mid-run user message is an interjection, not a stop: answer it briefly and, '
                              'in the same reply, continue the run — re-read the phase todo when one is '
                              'active and dispatch or advance the next pending step, or name the armed wait '
                              'it is waiting on -- handle, bound completion signal, deadline -- instead of '
                              "re-reading status. Only the user's explicit stop or cancel, or the engine's "
                              'own completion gate, ends the run; when the interjection changes scope, say '
                              'so and update the declared plan or todo instead of silently abandoning it. A '
                              'mid-run message is the latest steering for the active task, not automatically '
                              'a replacement objective: it replaces the objective when the user says so and '
                              'steers the current one otherwise.',
                              'A follow-up that needs new authority, materially expands the scope, or '
                              'changes external state not already authorized is described first and started '
                              "only on the user's approval; persistence never broadens the authorized scope. "
                              'A refused escalation gets a safer alternative inside the boundary, or the '
                              'authorization the boundary asks for — never a workaround or an indirect '
                              'execution.',
                              'The closing brief scales to the change: one or two sentences plus the '
                              'observed validation for a simple change, more only when the complexity earns '
                              'it. Lead with the result or decision; omit abandoned approaches unless they '
                              'explain a tradeoff the reader needs; narrate no internal bookkeeping (todo '
                              'transitions, follow-up declarations, waits). Required closing lines stay '
                              'outside this scaling: the observed run summary, and any prepared-not-observed '
                              "or unmerged work, are stated whatever the brief's length.",
                              'Expose core OMH roles: interviewer, planner, researcher, builder, reviewer, '
                              'and loop controller.',
                              'Route tiny direct tasks to one-cycle delivery surfaces instead of forcing '
                              'loop overhead.',
                              'Reframe a north-star ambition into a bounded arena, observable problem, next '
                              'loop goal, and next verification without shrinking its ambition.',
                              'Separate task discovery, distribution, execution, verification, next-task '
                              'decision, runtime tick queueing, durable-checkpoint/handoff, feedback, '
                              'waiting, and resume decisions.',
                              'Expose a permission profile before executor/runtime dispatch, repository '
                              'mutation, PR, merge, or external publishing.',
                              'Expose the automation, worktree, skill, connector, and subagent '
                              'building-block states without treating planned blocks as observed work.',
                              'Choose workflow patterns such as single-step, fan-out-and-synthesize, '
                              'adversarial verification, tournament, or triage batch as orchestration '
                              'metadata only.',
                              'Keep repeated scaffold shape stable, summarize within bounded budgets, and '
                              'add verifier lanes only when risk or evidence warrants them.',
                              'Keep prepared worktree/subagent/connector plans, observed executor work, '
                              'linked goal completion, and external waiting as distinct evidence states.',
                              'Use cheap inner-loop checks frequently and expensive outer-loop checks '
                              'sparingly.',
                              'Keep the practical small-loop recipe visible: test as stop signal, plan -> '
                              'execute -> verify, one task at a time.',
                              'Surface verification_gap, comprehension_debt, and cognitive_surrender as '
                              'warnings before a loop starts looking self-steering.',
                              'Use `omh loop assess`, `start`, `status`, `tick`, and `feedback` as local '
                              'metadata control-plane commands. Execute authorized work through the current '
                              'host. The default hermes_goal driver label is prepared metadata, not an '
                              'available host goal controller. Do not invoke native /goal controls on '
                              'another host.',
                              'Only an explicitly selected coding owner with a session-bound host_observed '
                              'resumable_goal capability may use the external goal-driver CLI path. '
                              'Otherwise keep a host-owned evidence ledger; report unavailable native goal '
                              'activation rather than fabricating it.',
                              'Treat ticks as preparation only. Record host phase results separately; never '
                              'manufacture native phase-transition evidence from a host task declaration.',
                              'Treat a judge `done` verdict, a turn-ceiling pause, or a gate-retry pause as '
                              'narration; completion still requires the linked goal ledger completion gate '
                              'and observed evidence.',
                              'Treat any future change to the default as a maintainer-reviewed product '
                              'decision, not a runtime phase or automatic loop outcome.',
                              'Compare only observed outcomes under matched task, model/provider, '
                              'permissions, turn budget, and verification surface; unresolved evidence keeps '
                              'the current default.',
                              'Keep promotion governance separate from goal-ledger completion and ordinary '
                              'measured-loop keep/discard decisions; do not invent subjective scorers, fixed '
                              'numeric thresholds, minimum run counts, weighted percentages, or per-turn '
                              'artifact quotas.',
                              'Name the one element gating this loop from the '
                              '`loop_constraint_assessment/v1` block before choosing the next action; if '
                              'none is binding, say so from the recorded reason rather than assuming.',
                              'When the goal is measurable, declare the evaluation contract before the first '
                              'attempt - exact command, metric name, direction, and the rule that the loop '
                              'may not modify the scoring harness - and bind every keep or discard decision '
                              'to it; when no such contract exists, say the goal is unmeasured instead of '
                              'scoring it by judgement.',
                              'Run a measurable cycle as attempt, commit, measure, then keep or reset; a '
                              'reset is the normal discard, and rewinding to an older commit is for a run of '
                              'discards that traces to one bad ancestor.',
                              'For a measurable loop, keep a human-scannable ledger the loop itself appends '
                              'to - one tab-separated line per cycle carrying commit, metric, cost, keep or '
                              'discard or crash, and a one-line description - beside the JSON loop '
                              'artifacts.',
                              'Send long-running cycle output to a log file and pull only the declared '
                              'metric and error lines into context; read the whole log only when the cycle '
                              'crashed.',
                              'Choose the wait strategy before starting long-running work and bind it to a '
                              'completion signal the host exposes, never to a status loop: a command that '
                              'fits one tool call runs once in the foreground with a duration-sized timeout; '
                              'a longer terminal command runs in the background with completion notification '
                              'armed and no process-status polling; a delegated lane relies on its delivered '
                              'result while the parent continues independent work or ends the turn; a CI, '
                              'PR, deploy, file, port, log-line, or external-session condition uses the '
                              "host's monitor when observed, else exactly ONE bounded watcher or adaptive "
                              'backoff outside model turns. Record the handle and observation mode at '
                              'dispatch; every armed wait needs a hard deadline, a cancellation path, and a '
                              'fallback naming the missing capability. Each wait closes in one terminal '
                              'state with bounded evidence; an unbounded idle or busy-wait is a defect and a '
                              'lost notification times out. One decision-changing midpoint peek and any '
                              'user-requested status check stay allowed; neither is the wait mechanism. '
                              'Ladder and terminal states: shared rail.',
                              'On an equal metric keep the simpler change, always keep an improvement '
                              'achieved by deletion, and do not let a small gain buy added complexity.'),
              'expected_outputs': ('loopability_assessment/v1 task/project/ambition classification',
                                   'loop_start_card/v1 setup prompt',
                                   'loop_cycle/v2',
                                   'loop_engineering/v1 pipeline/building-block snapshot',
                                   'loop verification_policy for inner/outer checks',
                                   'loop failure_mode_summary over verification gap, comprehension debt, and '
                                   'cognitive surrender',
                                   'small-loop guidance: test as stop signal, plan -> execute -> verify, one '
                                   'task at a time',
                                   'loop_status_card/v1 next action',
                                   'loop_runtime/v1 queued tick with verification_plan refs',
                                   'loop_queue_handoff/v1 only when permitted',
                                   'executor-neutral handoff only when permitted',
                                   'external-wait or checkpoint boundary',
                                   'host-owned continuation ledger; optional external goal-driver handoff '
                                   'only with an observed supported capability',
                                   'observed host task results kept separate from unsupported native goal '
                                   'observations',
                                   'host phase ledger with evidence references, not fabricated native phase '
                                   'transitions'),
              'artifact_expectations': ('loop_cycle/v2: loop_driver/v1 and loopability_assessment/v1 '
                                        'metadata',
                                        'loop_engineering/v1 status over automation, worktree, skill, '
                                        'connector, subagent, verification policy, and failure modes',
                                        'loop_runtime/v1 queue entries with context_policy_ref, '
                                        'cost_policy_ref, and verification_plan',
                                        'loop_subagent_result_contract/v1 for prepared subagent handoffs',
                                        'loop_status_card/v1 local status; native-goal fields remain '
                                        'not_observed on other hosts',
                                        'loop_start_card/v1 wrapper setup card',
                                        'linked goal_ledger/v1 only when completion evidence is required',
                                        'optional external goal-driver handoff only with observed '
                                        'session-bound support',
                                        'optional advisory external snapshots via goal-driver-observe; no '
                                        'native history is inferred',
                                        'host-owned phase/result evidence ledger, separate from native '
                                        'loop_phase_transition/v1'),
              'final_checklist': ('The request is classified as task, project, north-star ambition, '
                                  'external-wait, or unclear before a loop starts.',
                                  'The current loop_status_card/v1 names the queue item, tick status, '
                                  'verification_plan, and next action.',
                                  'failure_mode_summary checks verification_gap, comprehension_debt, and '
                                  'cognitive_surrender before progress advances.',
                                  'Completion is backed by linked goal/runtime evidence; queued loop ticks '
                                  'alone are not observed work.',
                                  'Native goal activation remains unavailable unless independently observed '
                                  'in its owning runtime; host results never substitute for native '
                                  'activation or contiguous-turn evidence.'),
              'recovery_notes': ('Drive the loop lifecycle through a native loop tool when this host offers '
                                 'one, submitting the revision the last read reported; the OMH native loop '
                                 'tool is unavailable in this projection, so keep the durable ledger with '
                                 'the host commands instead.',
                                 'If a queued tick is pending, show it as prepared queue state and use loop '
                                 'status/run-once before claiming progress.',
                                 'If feedback is unclear, ask one gate question or route back to '
                                 'research/plan rather than advancing the loop.',
                                 'If the goal turns into external waiting, record the waiting state and next '
                                 'observable signal instead of continuing locally.',
                                 'Checkpoint on context/budget exhaustion. Migrate loop_cycle/v1 with '
                                 'migrate-driver --apply before external binding.',
                                 "Resume the current host's durable checklist from observed evidence. If "
                                 'native goal control is requested on an unsupported host, report '
                                 'unavailable instead of inventing activation.',
                                 'If the loop runs out of next actions, re-read the scoped files, recombine '
                                 'the near-miss attempts, then escalate to a more radical change before '
                                 'declaring the loop blocked.'),
              'why_this_exists': ('`loop` exists for goals whose correct implementation cannot be known '
                                  'upfront but can be discovered through bounded cycles of definition, '
                                  'action, verification, and revision without confusing planned cycles with '
                                  'observed progress.',)},
 'ulw-qa': {'quality_bar': ("Do not start this engine as an automatic continuation of another skill's "
                            'output: an accepted plan, a clarified brief, or a routing recommendation is '
                            'planning evidence, not permission. Unless the user explicitly invoked this '
                            'engine themselves, restate in one line what will start (engine, scope, selected '
                            "executor) and wait for the user's explicit go-ahead first.",
                            'A mid-run user message is an interjection, not a stop: answer it briefly and, '
                            'in the same reply, continue the run — re-read the phase todo when one is active '
                            'and dispatch or advance the next pending step, or name the armed wait it is '
                            'waiting on -- handle, bound completion signal, deadline -- instead of '
                            "re-reading status. Only the user's explicit stop or cancel, or the engine's own "
                            'completion gate, ends the run; when the interjection changes scope, say so and '
                            'update the declared plan or todo instead of silently abandoning it. A mid-run '
                            'message is the latest steering for the active task, not automatically a '
                            'replacement objective: it replaces the objective when the user says so and '
                            'steers the current one otherwise.',
                            'A follow-up that needs new authority, materially expands the scope, or changes '
                            'external state not already authorized is described first and started only on '
                            "the user's approval; persistence never broadens the authorized scope. A refused "
                            'escalation gets a safer alternative inside the boundary, or the authorization '
                            'the boundary asks for — never a workaround or an indirect execution.',
                            'The closing brief scales to the change: one or two sentences plus the observed '
                            'validation for a simple change, more only when the complexity earns it. Lead '
                            'with the result or decision; omit abandoned approaches unless they explain a '
                            'tradeoff the reader needs; narrate no internal bookkeeping (todo transitions, '
                            'follow-up declarations, waits). Required closing lines stay outside this '
                            'scaling: the observed run summary, and any prepared-not-observed or unmerged '
                            "work, are stated whatever the brief's length.",
                            'Generate hostile scenarios from changed behavior and known risk areas.',
                            'Report pass/fail evidence separately from proposed fixes.',
                            'Delegate code mutations discovered by QA to the selected coding executor.',
                            'Read actual host/executor evidence before claiming build, verification, review, '
                            'documentation, or PR-preparation results.'),
            'why_this_exists': ('`ultraqa` exists to keep `verification` work explicit, evidence-backed, and '
                                'inside the host/executor boundary instead of relying on ad hoc chat '
                                'narration.',)},
 'ulw-context': {
     'artifact_expectations': (
         'Optional human-reviewed PROJECT_TERMS.md patch proposal; never write it automatically.',
         'Pending domain-intelligence candidates only after explicit staging confirmation.',
         'Prepared ulw-plan or selected coding-owner handoff only after separate confirmation.',
         'Load references/project-terms.md for source authority and capture; load '
         '`references/decision-frontier.md` before interviewing for the dependency-ready '
         'batch protocol, stable decision IDs, round bounds, consent gates, and compaction recovery.',
     ),
     'why_this_exists': ('`context` exists to reduce repository terminology drift without '
                                     'creating a second machine store or a vocabulary router: the host can '
                                     'answer lookups, facilitate dependency-aware alignment, and project '
                                     'approved results into existing review and handoff boundaries.',)},
 'ulw-interview': {
     'artifact_expectations': (
         'A host-owned clarity summary: outcome, constraints/non-goals, and success criteria '
         'are the three fixed dimensions; report resolved/3, never an expanding denominator.',
         'Track the round in the current thread, ask one decision-changing question with '
         'two to four candidate answers plus free input, and honor the catalog round ceiling. '
         'Stop on clarity, user stop, or budget exhaustion; summarize unresolved assumptions '
         'rather than restarting after lost context. Summary confirmation is not execution approval.',
     ),
     'why_this_exists': ('`deep-interview` exists to stop the host from guessing through '
                                       'ambiguous product, workflow, or implementation intent; it converts '
                                       'uncertainty into a clarified brief before planning or handoff.',)},
 'ulw-research': {'why_this_exists': ('`research` exists to make the host a careful research engine: it '
                                      'routes research demands to source-backed evidence gathering - from '
                                      'live web citations to studied reference implementations - verifies '
                                      'contested claims, and distills decision-grounding output so planning '
                                      'starts from evidence instead of guesses.',)},
 'ulw-perf': {'why_this_exists': ('`ultraperf` exists because most performance work starts unlocalized: '
                                  'something is slow, leaking, or expensive and nobody knows where. It '
                                  'forces measurement before edits, one hypothesis at a time, executor-owned '
                                  'changes, and a regression budget, so an optimization loop cannot end in '
                                  'unverified claims.',)},
 'omh-adversarial-consensus': {'artifact_expectations': ('Record the distilled bundle in a durable '
                                                         'host-owned or repository file so the planner '
                                                         'consumes an artifact, not scrollback.',)},
 'omh-memory-new': {'safety_rules': ('An OMH project-memory candidate is prepared local context only, not an '
                                     'approved record or native host-memory mutation. External '
                                     'provider/vector and host context is not_omh_reviewed and can nominate '
                                     'a candidate only.',
                                     'Do not claim connector, gateway, runtime, file generation, memory '
                                     'mutation, or host automation evidence from prepared guidance.',
                                     'Remember only one bounded durable candidate; refuse secrets, raw logs, '
                                     'transcripts, prompt-injection-shaped instructions, and temporary '
                                     'progress.',
                                     'Defer uncertain source, scope, target, retention, and external '
                                     'provider/vector content to review; not_omh_reviewed context never '
                                     'inherits OMH approval.')},
 'omh-report-package': {'expected_outputs': ('report package',
                                             'PPT-ready Markdown or JSON outline',
                                             'assumptions and missing-input list',
                                             'Optional supplied achievements summary when requested; '
                                             'plugin-backed badge retrieval is unavailable in this '
                                             'projection.')},
 'omh-paper-learning': {'recovery_notes': ('If no paper text is observed, prepare the learning card from '
                                           'metadata only and ask for an attachment, excerpt, or extraction '
                                           'evidence.',
                                           'If only an abstract or excerpt is supplied, label the result as '
                                           'excerpt explanation and list missing sections.',
                                           'If context is too long, continue section-by-section and keep '
                                           'covered / next / missing state in the ledger.',
                                           'If the paper is longer than one read window, plan numbered page '
                                           'or line ranges in a durable host-owned ledger before reading, '
                                           'walk them in order, and mark each covered; the native OMH plan '
                                           'tool is unavailable in this projection.',
                                           'If the user asks for validation, citation checking, math proof '
                                           'review, or reproduction, create a separate observed-evidence or '
                                           'coding handoff path.')}}

# Reviewed domain procedures and methods. Omitted: router/wrapper/backend rails,
# native campaign/TDD RPC guidance, route-capacity host injection, ecosystem
# installation recipes, and progressive full-contracts (inlined for this target).
PORTABLE_REFERENCE_PATHS = frozenset({
    'wiki/references/wiki-blueprint.md',
    'wiki/references/wiki-patterns.md',
    'wiki/references/wiki-operations.md',
    'code-review/references/review-dispatch.md',
    'code-review/references/review-response.md',
    'code-review/references/smell-baseline.md',
    'context/references/project-terms.md',
    'context/references/decision-frontier.md',
    'context-budget-review/references/cache-placement.md',
    'loop/references/goal-constraint-discipline.md',
    'loop/references/measured-loop-discipline.md',
    'adversarial-consensus/references/consensus-protocol.md',
    'ultrawork/references/dependency-topology.md',
    'idea-to-deploy/references/project-bootstrap.md',
    'llm-app-dev/references/build-rails.md',
    'llm-app-dev/references/eval-harness.md',
    'llm-app-dev/references/public-board.md',
    'llm-app-dev/references/stateful-contracts.md',
    'finance-analysis/references/procedure.md',
    'legal-compliance-review/references/procedure.md',
    'curriculum-design/references/procedure.md',
    'sales-development/references/procedure.md',
    'decision-prototype/references/procedure.md',
    'lifecycle-growth/references/procedure.md',
    'product-discovery-validation/references/procedure.md',
    'sales-pipeline-review/references/procedure.md',
    'research/references/briefing-format.md',
    'frontend/references/design-system-contract.md',
    'frontend/references/taste-foundations.md',
    'frontend/references/reference-token-extraction.md',
    'frontend/references/tui-craft.md',
    'frontend/references/screenshot-loop.md',
    'frontend/references/web-vitals-budgets.md',
    'frontend/references/scroll-motion-libraries.md',
    'design-quality-gate/references/design-critique-rubric.md',
    'visual-qa/references/visual-verdict-contract.md',
    'apple-design/references/platform-foundations.md',
    'apple-design/references/materials-and-accessibility.md',
    'apple-design/references/product-visual-production.md',
    'apple-design/references/web-production-libraries.md',
    'apple-design/references/review-playbook.md',
    'award-bar-score/references/award-judging-model.md',
    'agent-ops-review/references/instrumentation-ladder.md',
    'inference-serving/references/serving-runbooks.md',
    'inference-serving/references/serving-bench.md',
    'tech-debt-audit/references/debt-dimensions.md',
    'accessibility-audit/references/a11y-rules.md',
    'strategy-brief/references/decision-records.md',
    'refactor-plan/references/refactor-phases.md',
    'frontend-refactor/references/refactor-passes.md',
    'frontend-refactor/references/state-discipline.md',
    'ai-slop-cleaner/references/cleanup-passes.md',
    'backend/references/service-contract.md',
    'backend/references/schema-migration.md',
    'rust/references/rust-discipline.md',
    'rust/references/ub-escalation.md',
    'native-debugging/references/native-debug-loop.md',
    'application-threat-model/references/threat-model-method.md',
    'live-incident-response/references/incident-command-method.md',
})
