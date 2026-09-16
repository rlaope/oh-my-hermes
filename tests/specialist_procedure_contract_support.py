TARGETS = frozenset(
    {
        "finance-analysis",
        "legal-compliance-review",
        "sales-development",
        "curriculum-design",
        "decision-prototype",
        "lifecycle-growth",
        "product-discovery-validation",
        "sales-pipeline-review",
    }
)

DOMAIN_REVIEW_CONTRACTS = {
    "finance-analysis": {
        "outputs": (
            "finance_scope_source_record/v1",
            "finance_reconciliation_analysis_schedule/v1",
            "finance_risk_register/v1",
            "finance_decision_brief/v1",
        ),
        "steps": (
            "finance_scope_sources",
            "finance_reconcile_sources",
            "finance_analyze_variances",
            "finance_interpret_conditionally",
            "finance_validate_brief",
        ),
        "checks": {
            "finance_scope_comparability_check": {"entity_perimeter", "period_cutoff", "currency_units", "accounting_basis", "comparator_version", "close_status", "source_provenance"},
            "finance_source_reconciliation_check": {"totals_status", "account_mapping_status", "basis_units_status", "cutoff_status", "duplicate_missing_status", "tie_out_status", "unreconciled_gaps"},
            "finance_policy_assumption_check": {"formula_provenance", "policy_provenance", "materiality_status", "fx_allocation_treatment", "assumption_approval_status"},
            "finance_conditional_interpretation_check": {"analysis_applicability", "revenue_bridge_status", "receivables_dso_status", "working_capital_status", "unavailable_evidence"},
            "finance_validation_escalation_check": {"recalculation_status", "reconciliation_status", "source_conflicts", "control_exceptions", "high_impact_assumptions", "disposition", "escalation_owner"},
        },
    },
    "legal-compliance-review": {
        # The redline output mode (#1579). Its output sits where its step
        # produces it, not appended: this contract asserts outputs and steps as
        # ordered tuples, and the disposition stays last because it is the
        # terminal verdict.
        "outputs": (
            "legal_scope_authority_record/v1",
            "legal_issue_traceability_matrix/v1",
            "legal_risk_counsel_hold_register/v1",
            "legal_negotiation_preparation/v1 when the objective is a redline rather than an assessment",
            "legal_review_disposition/v1",
        ),
        "steps": (
            "legal_scope_facts_instruments",
            "legal_trace_authority",
            "legal_map_issues_exceptions",
            "legal_apply_counsel_holds",
            "legal_prepare_negotiation_positions",
            "legal_validate_disposition",
        ),
        "checks": {
            "legal_scope_facts_instruments_check": {"actors_roles", "operative_facts", "instrument_set", "order_of_precedence", "governing_law_forum", "regulatory_jurisdictions", "execution_effective_as_of_dates", "assumptions_blockers"},
            "legal_authority_citation_check": {"source_type", "source_identifier", "source_version", "effective_status", "pinpoint", "operative_text_summary", "verification_status"},
            "legal_issue_matrix_check": {"applicability_facts", "obligation_position", "definitions_dependencies", "exceptions_carveouts_conflicts", "evidence_status", "risk_uncertainty", "action_owner", "recommended_disposition", "counsel_question", "issue_family_applicability"},
            "legal_counsel_hold_check": {"trigger_ids", "impact", "likelihood_applicability", "urgency", "evidence_confidence", "reversibility", "hold_status", "counsel_owner"},
            "legal_negotiation_preparation_check": {"playbook_position", "gap", "proposed_language", "fallback_position", "walk_away_trigger", "concession_order", "counsel_hold_state"},
            "legal_final_determination_guard": {"invented_authority_status", "stale_authority_status", "unresolved_triggers", "disposition"},
        },
    },
    "sales-development": {
        "outputs": (
            "sales_opportunity_evidence_record/v1",
            "sales_qualification_state/v1",
            "sales_draft_sequence/v1",
            "sales_handoff_disposition/v1",
        ),
        "steps": (
            "sales_scope_account_evidence",
            "sales_build_qualification_state",
            "sales_check_sequence_eligibility",
            "sales_prepare_draft_sequence",
            "sales_validate_handoff",
        ),
        "checks": {
            "sales_account_evidence_check": {"fit_disqualifiers", "offer_use_case", "account_stage_owner", "stakeholder_states", "problem_current_approach_impact", "source_locator_date_reliability_permission", "contradictions", "unknowns", "claim_evidence_state"},
            "sales_qualification_state_check": {"stakeholder_authority_state", "problem_current_state", "measurable_impact", "decision_criteria_process", "alternatives", "timing_urgency", "risks_blockers", "champion_economic_buyer_hypotheses", "prioritized_questions", "buyer_confirmation_evidence", "disposition"},
            "sales_sequence_eligibility_check": {"consent_basis", "privacy_constraints", "suppression_status", "channel_eligibility", "policy_constraints", "audience_persona", "timing_cadence", "evidence_backed_personalization", "approved_proof", "purpose_value_cta", "objection_hypothesis", "validation_question", "owner_approver", "stop_opt_out_reply_conditions", "draft_status"},
            "sales_handoff_check": {"proposed_confirmed_status", "action", "owner", "approver", "target_timing", "success_exit_criterion", "dependencies", "evidence_refs", "crm_object_field_value_proposals", "unresolved_gaps", "disposition"},
        },
    },
    "curriculum-design": {
        "outputs": (
            "curriculum_learner_outcome_brief/v1",
            "curriculum_alignment_map/v1",
            "curriculum_sequence_design/v1",
            "curriculum_validation_disposition/v1",
        ),
        "steps": (
            "curriculum_frame_learners_outcomes",
            "curriculum_define_evidence_criteria",
            "curriculum_design_sequence_scaffolds",
            "curriculum_validate_alignment",
            "curriculum_revise_revalidate",
        ),
        "checks": {
            "curriculum_intake_readiness_check": {"learner_setting", "baseline_evidence", "motivation_goals", "language_culture", "access_variability", "outcome_performance_conditions_criteria_transfer", "prerequisite_misconception_diagnostic_remediation", "delivery_policy_constraints"},
            "curriculum_outcome_evidence_alignment_check": {"outcome_id", "performance_condition_criterion", "assessment_evidence", "rubric_criteria", "formative_checks", "coverage_status", "orphan_mismatch_insufficient_evidence"},
            "curriculum_scaffolding_inclusion_check": {"activation_diagnosis", "modeling_examples", "guided_practice", "feedback", "independent_transfer", "scaffold_removal", "accessible_formats_interactions", "language_cultural_support", "technology_barriers", "accommodations_flexible_paths", "equivalent_demonstration", "barrier_addressed"},
            "curriculum_validation_revision_check": {"criterion_id", "status", "exact_gaps", "learner_impact", "required_revision", "owner_decision", "unresolved_evidence", "revalidation_checks", "review_pilot_plan", "evidence_state"},
        },
    },
    "decision-prototype": {
        "outputs": ("decision_prototype/v1", "prepared prototype handoff with exact commands and expected observations", "observation ledger separating observed outputs from interpretation and confidence", "decision receipt for planning with supported option, rejected option, residual risk, and evidence limits"),
        "steps": ("prototype_frame_decision", "prototype_bound_experiment", "prototype_prepare_handoff", "prototype_record_observations", "prototype_close_receipt"),
        "checks": {
            "prototype_scope_check": {"target_user_task", "hypothesis_falsifiable", "alternatives", "decision_question", "decision_id", "scope_disposition"},
            "prototype_budget_isolation_check": {"executor_runtime", "command_budget", "workspace_identity", "tool_budget", "file_budget", "time_budget", "write_boundary_status", "capability_limits"},
            "prototype_smallest_artifact_check": {"measurement_method", "artifact_kind", "stop_conditions", "expansion_refused", "fixture_data_class"},
            "prototype_execution_evidence_check": {"evidence_refs", "unresolved_questions", "confidence", "interpretation", "execution_status", "observed_outputs"},
            "prototype_cleanup_receipt_check": {"prototype_code_reference_permission", "evidence_limits", "keep_discard_decision", "supported_option", "residual_risk", "rejected_option", "cleanup_status", "promotion_status"},
        },
    },
    "lifecycle-growth": {
        "outputs": ("lifecycle_growth_brief/v1", "audience_trigger_policy/v1", "lifecycle_safety_policy/v1", "growth_experiment_plan/v1", "growth_measurement_readout/v1", "growth_handoff_disposition/v1"),
        "steps": ("lifecycle_define_target_behavior", "lifecycle_scope_audience_triggers", "lifecycle_check_safety_eligibility", "lifecycle_design_experiment", "lifecycle_prepare_measurement_readout", "lifecycle_validate_handoff"),
        "checks": {
            "lifecycle_target_behavior_check": {"evidence_refs", "lifecycle_stage", "hypotheses", "owner", "baseline_value", "baseline_window", "target_behavior", "disposition", "non_goals"},
            "lifecycle_audience_eligibility_check": {"entry_conditions", "exit_conditions", "event_semantics_status", "idempotency_key", "reentry_policy", "collision_policy", "denominator_status", "canonical_events", "disposition", "exclusions", "identity_key"},
            "lifecycle_safety_eligibility_check": {"consent_basis", "locale", "global_frequency_budget", "suppression_precedence", "user_preferences", "disposition", "quiet_hours", "channel_eligibility", "campaign_frequency_budget", "legal_tenant_constraints", "throttle_grouping", "workflow_content_state", "promotion_decision"},
            "lifecycle_experiment_validity_check": {"primary_metric", "exposure_definition", "assignment_unit", "treatment_control", "exposure_unit", "guardrail_metrics", "pause_rollback_conditions", "assignment_stickiness", "data_health_checks", "approval_state", "holdout_rationale", "minimum_runtime"},
            "lifecycle_readout_evidence_check": {"evidence_refs", "cross_exposure_status", "displayed_count", "overlap_status", "freshness_status", "causal_claim_status", "delivered_count", "instrumentation_status", "denominator_status", "sample_ratio_status", "acted_count", "eligible_count", "disposition", "attempted_count", "outcome_count", "step_outcomes", "step_trace_status", "analysis_run_state", "analysis_observed_at", "analysis_delay_status", "exposure_evidence", "assigned_count", "repeated_contact_count", "contact_pressure_state", "channels"},
            "lifecycle_handoff_boundary_check": {"approver", "evidence_refs", "action_class", "target_owner", "readiness", "disposition", "timing", "stop_conditions", "approval_state", "analysis_cancellation"},
        },
    },
    "product-discovery-validation": {
        "outputs": ("discovery_decision_frame/v1", "discovery_evidence_ledger/v1", "customer_discovery_plan/v1", "assumption_test_portfolio/v1", "discovery_decision_receipt/v1", "initial_gtm_hypothesis/v1"),
        "steps": ("discovery_frame_decision", "discovery_classify_evidence", "discovery_plan_customer_reentry", "discovery_gate_problem", "discovery_rank_assumptions", "discovery_draft_gtm_hypothesis", "discovery_validate_decision_receipt"),
        "checks": {
            "discovery_decision_frame_check": {"owner", "current_alternatives", "problem_hypothesis", "decision", "kill_criteria", "disposition", "constraints", "learning_budget", "segment", "target_segment_definition"},
            "discovery_evidence_class_check": {"unresolved_inconsistency", "pointer_status", "direction", "safe_reference", "source_class", "confidence_limits", "observation", "segment", "observation_date"},
            "discovery_customer_reentry_check": {"interview_guide_focus", "human_task_handoff", "transcript_exclusion", "participant_criteria", "consent_privacy_constraints", "evidence_reentry_contract", "bias_controls"},
            "discovery_problem_gate_check": {"gate_reason", "problem_gate_state", "solution_work_permitted", "supporting_refs", "contradicting_refs", "audience_gate", "missing_audience_evidence"},
            "discovery_assumption_precommit_check": {"evidence_gap", "smallest_disconfirming_test", "segment_sample", "success_condition", "cost", "owner", "assumption_category", "evidence_reentry", "deadline", "inconclusive_condition", "failure_condition", "decision_impact", "rank"},
            "discovery_decision_receipt_check": {"promotion_guard", "next_route", "rejected_paths", "decision", "residual_risks", "confidence_limits", "observed_evidence", "precommitted_criteria"},
            "discovery_gtm_hypothesis_check": {"pricing_wtp_hypothesis", "current_alternative", "value_proposition", "first_cohort", "buyer_user_distinction", "beachhead_segment", "learning_metrics", "initial_channel", "evidence_basis"},
        },
    },
    "sales-pipeline-review": {
        "outputs": ("sales_pipeline_scope/v1", "sales_pipeline_health/v1", "sales_forecast_assessment/v1", "sales_outcome_learning_annex/v1", "sales_renewal_risk_annex/v1", "sales_pipeline_handoff/v1"),
        "steps": ("sales_pipeline_validate_scope", "sales_pipeline_assess_health", "sales_pipeline_assess_forecast", "sales_pipeline_prepare_annexes", "sales_pipeline_validate_handoff"),
        "checks": {
            "sales_pipeline_scope_check": {"data_quality_gaps", "currency_conversion_basis", "freshness_status", "forecast_category_definitions", "amount_semantics", "included_motions_owners", "stage_definitions", "review_horizon_cohort", "source_reference", "duplicate_status", "disposition", "as_of_time", "missing_owner_status"},
            "sales_pipeline_health_check": {"concentration", "duplicates", "missing_ownership", "exit_criteria_evidence", "aging_stalls", "stage_movement", "next_step_quality", "slipped_close_dates", "record_evidence_refs", "deal_exceptions"},
            "sales_forecast_state_check": {"evidence_limits", "confidence", "scenario_range", "observed_buyer_commitment", "prior_forecast_actual_comparison", "supplied_probability", "calibration_status", "supplied_seller_category"},
            "sales_outcome_learning_check": {"unqualified_reasons", "contradictions", "cohort_bounds", "observed_lost_reasons", "annex_status", "research_followups", "missing_evidence", "observed_won_reasons"},
            "sales_renewal_risk_check": {"support_signal", "owner", "budget_signal", "health_signal", "staffing_signal", "open_risks", "annex_status", "utilization_signal", "expansion_hypotheses", "renewal_horizon"},
            "sales_pipeline_handoff_check": {"exit_criterion", "owner", "crm_object_field_value_proposals", "due_date", "evidence_ref", "sibling_routes", "disposition", "approval_state", "mutation_status", "selected_account_followups"},
        },
    },
}
