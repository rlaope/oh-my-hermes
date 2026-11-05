# curriculum-design Specialist Procedure

Expert clarification questions:
- `learners`
  - English: Which learner roles or ages and setting, baseline evidence, experience, motivations, language or culture, access needs, and relevant variability should shape the design?
  - Korean: 어떤 학습자 역할 또는 연령과 환경, 기초 수준 근거, 경험, 동기, 언어와 문화, 접근 요구, 관련 다양성이 설계에 반영되어야 하나요?
- `learning goal`
  - English: What observable learner performance, conditions, success criteria, transfer context, and priority or scope define the goal?
  - Korean: 어떤 관찰 가능한 학습자 수행, 조건, 성공 기준, 전이 맥락, 우선순위 또는 범위가 목표를 정의하나요?
- `prerequisites`
  - English: Which entry skills and knowledge can learners demonstrate, what diagnostic evidence and misconceptions exist, and what remediation path covers gaps?
  - Korean: 학습자가 입증할 수 있는 선수 기술과 지식, 진단 근거와 오개념, 부족한 부분을 보완할 경로는 무엇인가요?
- `constraints`
  - English: Which modality, cohort size, schedule, technology, accessibility, resources, assessment policy, or facilitator constraints apply?
  - Korean: 어떤 운영 방식, 학습자 규모, 일정, 기술, 접근성, 자원, 평가 정책 또는 진행자 제약이 적용되나요?

## Procedure

Declared checks:
- `curriculum_intake_readiness_check`
  - Required result fields: `learner_setting`, `baseline_evidence`, `motivation_goals`, `language_culture`, `access_variability`, `outcome_performance_conditions_criteria_transfer`, `prerequisite_misconception_diagnostic_remediation`, `delivery_policy_constraints`
  - Criterion: PASS intake only when learner variability, evidence-backed entry state, observable outcomes and relevant delivery constraints are design-ready; otherwise mark gaps and remediation assumptions.
- `curriculum_outcome_evidence_alignment_check`
  - Required result fields: `outcome_id`, `performance_condition_criterion`, `assessment_evidence`, `rubric_criteria`, `formative_checks`, `coverage_status`, `orphan_mismatch_insufficient_evidence`
  - Criterion: For every outcome map acceptable evidence and criteria before activities, reporting orphan outcomes, orphan assessments, level or condition mismatches and insufficient evidence.
- `curriculum_scaffolding_inclusion_check`
  - Required result fields: `activation_diagnosis`, `modeling_examples`, `guided_practice`, `feedback`, `independent_transfer`, `scaffold_removal`, `accessible_formats_interactions`, `language_cultural_support`, `technology_barriers`, `accommodations_flexible_paths`, `equivalent_demonstration`, `barrier_addressed`
  - Criterion: Design a domain-appropriate progression and inclusive access before final validation, linking each scaffold or adaptation to a learner barrier and preserving equivalent outcome evidence.
- `curriculum_validation_revision_check`
  - Required result fields: `criterion_id`, `status`, `exact_gaps`, `learner_impact`, `required_revision`, `owner_decision`, `unresolved_evidence`, `revalidation_checks`, `review_pilot_plan`, `evidence_state`
  - Criterion: Return PASS, REVISE, or BLOCKED per criterion, revise affected outcomes, evidence, sequence, scaffolds or access choices, and rerun affected checks; learner review or pilot plans remain prepared until observed.

### `curriculum_frame_learners_outcomes` (analysis)

Establish learner context, baseline and variability, then define a small outcome set with observable performance, conditions, criteria and transfer priority.

- Input refs: `learners`, `learning goal`, `prerequisites`, `constraints`
- Output refs: `curriculum_learner_outcome_brief/v1`
- Check IDs: `curriculum_intake_readiness_check`

### `curriculum_define_evidence_criteria` (production)

Before sequencing instruction, define acceptable assessment evidence, rubric criteria and formative decision points for every outcome and expose all coverage defects.

- Input refs: `learners`, `learning goal`, `prerequisites`, `constraints`
- Output refs: `curriculum_alignment_map/v1`
- Check IDs: `curriculum_outcome_evidence_alignment_check`
- If this step fails: tentative; still stands: `curriculum_learner_outcome_brief/v1`; hand back: Return the draft curriculum_alignment_map/v1 with orphan outcomes, unmatched assessments, performance-condition mismatches and missing rubric or formative evidence identified for revision.

### `curriculum_design_sequence_scaffolds` (production)

Design activities from the evidence backward, including diagnosis, modeling where useful, guided practice, feedback, independent transfer, scaffold fading, accessible formats and equivalent demonstration paths.

- Input refs: `learners`, `learning goal`, `prerequisites`, `constraints`
- Output refs: `curriculum_sequence_design/v1`
- Check IDs: `curriculum_scaffolding_inclusion_check`
- If this step fails: tentative; still stands: `curriculum_learner_outcome_brief/v1`, `curriculum_alignment_map/v1`; hand back: Return the draft curriculum_sequence_design/v1 with missing practice, feedback or scaffold fading and unaddressed learner barriers tied to the access or equivalent-demonstration choices needing revision.

### `curriculum_validate_alignment` (validation)

Record criterion-level PASS, REVISE, or BLOCKED findings, exact misalignments and learner impact, required revisions, owner decisions, evidence gaps, and bounded expert or learner review plans.

- Input refs: `learners`, `learning goal`, `prerequisites`, `constraints`
- Output refs: `curriculum_validation_disposition/v1`
- Check IDs: `curriculum_intake_readiness_check`, `curriculum_outcome_evidence_alignment_check`, `curriculum_scaffolding_inclusion_check`, `curriculum_validation_revision_check`
- If this step fails: unresolved; still stands: `curriculum_learner_outcome_brief/v1`; hand back: Return curriculum_validation_disposition/v1 with criterion-level gaps, learner impact, required revisions, owner decisions and missing evidence; expert or learner review plans remain prepared until observed.

### `curriculum_revise_revalidate` (validation)

Apply approved revisions to the affected artifacts, rerun the named checks, and retain BLOCKED whenever required evidence or review remains unobserved.

- Input refs: `learners`, `learning goal`, `prerequisites`, `constraints`
- Output refs: `curriculum_alignment_map/v1`, `curriculum_sequence_design/v1`, `curriculum_validation_disposition/v1`
- Check IDs: `curriculum_outcome_evidence_alignment_check`, `curriculum_scaffolding_inclusion_check`, `curriculum_validation_revision_check`
- If this step fails: unresolved; still stands: `curriculum_learner_outcome_brief/v1`, `curriculum_validation_disposition/v1`; hand back: Return the prior curriculum_validation_disposition/v1 with pending revisions, owner decisions and failed revalidation checks for the alignment map and sequence; keep required unobserved reviews BLOCKED.
