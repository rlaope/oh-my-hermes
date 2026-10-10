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
    # required_inputs: the wrong behaviour, the command that shows it, captured traces; expected_outputs: reproduction_record/v1 through fix_handoff/v1; the executor runs every probe, so nothing here needs a Hermes runtime.
    'omh-app-debugging': PORTABILITY_PORTABLE,
    # required_inputs: the diff, the repo template and log, the commands that ran; expected_outputs: drafted text from an evidence ledger; reading a repo and drafting text needs no Hermes runtime.
    'omh-commit-pr-authoring': PORTABILITY_PORTABLE,
    # required_inputs: branches, upstreams, what is pushed; expected_outputs: pushed_state_inventory/v1 and git_repair_plan/v1; the user or executor runs every git command, so no Hermes runtime is needed.
    'omh-git-workflow': PORTABILITY_PORTABLE,
    # required_inputs: engine, version, table sizes, observed plans; expected_outputs: plans and a readiness verdict; OMH never connects to a database, so no Hermes runtime is needed.
    'omh-relational-db': PORTABILITY_PORTABLE,
    # required_inputs: the event kind, the advisory or credential facts, observed evidence; expected_outputs: an event record, a containment plan, and a closure verdict; OMH never scans or rotates, so no Hermes runtime is needed.
    'omh-security-event-response': PORTABILITY_PORTABLE,
    # required_inputs: instruction files, commands, generated files, pitfalls; expected_outputs: a verification record and a region update the executor writes, so no Hermes runtime is needed.
    'omh-agent-instructions': PORTABILITY_PORTABLE,
    # required_inputs: the tool, environments, saved plan output, health signals; expected_outputs: drift, blast radius, cost, staged apply, gates, rollback prepared for an operator, so no Hermes runtime is needed.
    'omh-iac-change': PORTABILITY_PORTABLE,
    # required_inputs: the pipeline, the affected window, the sink key, known readers; expected_outputs: lineage, impact, idempotency, replay plan and gates prepared for an operator, so no Hermes runtime is needed.
    'omh-data-pipelines': PORTABILITY_PORTABLE,
    # required_inputs: the failing task and held-out examples, what cheaper fixes scored, the data's shape, the base model; expected_outputs: a fine-tune decision, method, data plan, baseline comparison and promotion gate prepared for an operator, so no Hermes runtime is needed.
    'omh-model-finetuning': PORTABILITY_PORTABLE,
    # required_inputs: platforms and build numbers, how signing is held, the shipped SDKs, the beta and its testers, observed crash figures; expected_outputs: signing, privacy, beta, rollout and hotfix plans prepared for an operator, so no Hermes runtime is needed.
    'omh-mobile-release': PORTABILITY_PORTABLE,
    # required_inputs: the control, its population, sampling guidance, materiality, observed evidence; expected_outputs: control, sample design, evidence requests, re-performance record and a criteria-derived grade prepared for an auditor, so no Hermes runtime is needed.
    'omh-internal-audit': PORTABILITY_PORTABLE,
    # required_inputs: changes, release mechanism, health signals, rollback mechanism; expected_outputs: a release plan with a rollback trigger and a readiness verdict; the host or CI executes, so no Hermes runtime is needed.
    'omh-release-cut': PORTABILITY_PORTABLE,
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
    # Catalog reference/retired surface, not an installable workflow; no Agent Skills projection in v1.
    'omh-best-practice-research': PORTABILITY_HERMES_ONLY,
    # Catalog reference/retired surface, not an installable workflow; no Agent Skills projection in v1.
    'omh-autoresearch-goal': PORTABILITY_HERMES_ONLY,
    # Catalog reference/retired surface, not an installable workflow; no Agent Skills projection in v1.
    'omh-performance-goal': PORTABILITY_HERMES_ONLY,
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
    'loop/references/loop-design-review.md',
    'adversarial-consensus/references/consensus-protocol.md',
    'ultrawork/references/dependency-topology.md',
    'idea-to-deploy/references/project-bootstrap.md',
    'llm-app-dev/references/build-rails.md',
    'llm-app-dev/references/eval-harness.md',
    'llm-app-dev/references/public-board.md',
    'llm-app-dev/references/stateful-contracts.md',
    'finance-analysis/references/procedure.md',
    'legal-compliance-review/references/procedure.md',
    'legal-compliance-review/references/negotiation-preparation.md',
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
    'frontend/references/component-registry-adoption.md',
    'frontend/references/chart-styling.md',
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
    'strategy-brief/references/capacity-planning.md',
    'refactor-plan/references/refactor-phases.md',
    'refactor-plan/references/dependency-upgrade.md',
    'frontend-refactor/references/refactor-passes.md',
    'frontend-refactor/references/state-discipline.md',
    'ai-slop-cleaner/references/cleanup-passes.md',
    'backend/references/service-contract.md',
    'backend/references/schema-migration.md',
    'backend/references/consumer-impact.md',
    'rust/references/rust-discipline.md',
    'rust/references/ub-escalation.md',
    'native-debugging/references/native-debug-loop.md',
    'app-debugging/references/hypothesis-and-race-method.md',
    'commit-pr-authoring/references/commit-and-pr-conventions.md',
    'git-workflow/references/git-repair-method.md',
    'relational-db/references/engine-lock-tables.md',
    'security-event-response/references/event-containment-order.md',
    'agent-instructions/references/instruction-file-method.md',
    'iac-change/references/iac-change-method.md',
    'data-pipelines/references/pipeline-method.md',
    'model-finetuning/references/finetuning-method.md',
    'mobile-release/references/mobile-release-method.md',
    'internal-audit/references/control-audit-method.md',
    'release-cut/references/release-and-rollback-method.md',
    'application-threat-model/references/threat-model-method.md',
    'live-incident-response/references/incident-command-method.md',
    'external-connector-readiness/references/memory-provider-trial.md',
    'verification-gate/references/generated-artifact-provenance.md',
    'security-safety-review/references/credential-rotation.md',
    # Issue #1714. Each of these is named by a body pointer that projects into
    # this target, so omitting it would ship a pointer at a file the portable
    # pack does not carry. All five are host-neutral prose procedure: no OMH
    # CLI command, no Hermes-only surface, nothing that reads local state.
    # `ultrawork/references/file-ownership-manifest.md` is deliberately absent
    # -- the ulw-work override drops the quality_bar line that names it, so
    # carrying the file here would add an unreferenced document.
    # `todo-checklist` is not a portable skill at all, so its sibling
    # reference has no projection to dangle in.
    'verification-gate/references/requirement-coverage-map.md',
    'deep-interview/references/ambiguity-taxonomy.md',
    'code-review/references/review-lenses.md',
    'ai-slop-cleaner/references/prose-lexicon.md',
    'plan/references/project-constitution.md',
})
