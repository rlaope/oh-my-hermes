# decision-prototype Specialist Procedure

Expert clarification questions:
- `decision question`
  - English: Which single decision should this prototype settle, which alternatives are in play, and what observable result would falsify the preferred option?
  - Korean: 이 프로토타입으로 결정할 단일 의사결정은 무엇이고, 어떤 대안들이 있으며, 어떤 관찰 결과가 나오면 선호 옵션이 틀렸다고 볼 수 있나요?
- `experiment budget`
  - English: What time, tool, file, and command budget bounds the experiment, and which stop condition ends it even without an answer?
  - Korean: 이 실험을 제한하는 시간, 도구, 파일, 명령 예산은 무엇이고, 답이 없더라도 실험을 끝내는 중단 조건은 무엇인가요?
- `scratch boundary`
  - English: Which scratch directory or temporary worktree receives every write, which executor or runtime is available, and does any write outside that boundary have explicit approval?
  - Korean: 모든 쓰기가 들어갈 스크래치 디렉터리 또는 임시 워크트리는 무엇이고, 어떤 실행기나 런타임을 사용할 수 있으며, 그 경계 밖 쓰기에 명시적 승인이 있나요?
- `measurement method`
  - English: How will the result be measured, which target user or task applies when usability is involved, and which fixture or sample limits how far the result generalizes?
  - Korean: 결과를 어떻게 측정하고, 사용성이 걸린 경우 대상 사용자나 과제는 무엇이며, 어떤 픽스처나 샘플이 결과의 일반화 범위를 제한하나요?

## Procedure

Declared checks:
- `prototype_scope_check`
  - Required result fields: `decision_id`, `decision_question`, `alternatives`, `hypothesis_falsifiable`, `target_user_task`, `scope_disposition`
  - Criterion: PASS only when exactly one decision question carries a stable decision id, at least two alternatives, and a falsifiable hypothesis; otherwise HOLD, refuse the unbounded or multi-feature experiment, and ask for or derive one question.
- `prototype_budget_isolation_check`
  - Required result fields: `time_budget`, `tool_budget`, `file_budget`, `command_budget`, `executor_runtime`, `capability_limits`, `workspace_identity`, `write_boundary_status`
  - Criterion: Record every budget with a unit, the selected executor or runtime and its observed capability limits, and the scratch directory or temporary worktree identity; HOLD when a write would leave that boundary without explicit user approval or when the observed workspace does not match the declared one.
- `prototype_smallest_artifact_check`
  - Required result fields: `artifact_kind`, `measurement_method`, `stop_conditions`, `fixture_data_class`, `expansion_refused`
  - Criterion: Choose the smallest artifact that can answer the question (wireframe, CLI spike, API probe, fixture, timing probe, test harness, or mocked interaction), use synthetic fixtures by default, and refuse expansion into general feature implementation.
- `prototype_execution_evidence_check`
  - Required result fields: `execution_status`, `observed_outputs`, `evidence_refs`, `interpretation`, `confidence`, `unresolved_questions`
  - Criterion: When no executor is available, emit the prepared handoff and report results as unobserved; when execution occurred, record only observed outputs and bounded evidence references, keep interpretation and confidence separate, and mark timeout or inconclusive runs as such; tool success is never product validation. A performance or concurrency probe fixes its pass threshold before the run, warms up once, repeats at least five times and records min, median and max of the repeats, plus p95 over the requests inside a run when it issues many, and machine load; fewer runs are inconclusive.
- `prototype_cleanup_receipt_check`
  - Required result fields: `keep_discard_decision`, `cleanup_status`, `supported_option`, `rejected_option`, `residual_risk`, `evidence_limits`, `prototype_code_reference_permission`, `promotion_status`
  - Criterion: Report `discarded` only after cleanup is observed and record cleanup failure distinctly; the receipt names the supported option, rejected option, residual risk, evidence limits, and whether prototype code may be referenced, and promotion stays blocked until a separate accepted plan and implementation handoff exist.

### `prototype_frame_decision` (analysis)

Reduce the uncertainty to one decision question with a stable decision id, the alternatives, a falsifiable hypothesis, and the target user or task when usability is involved; refuse or split anything broader before spending budget.

- Input refs: `decision question`, `measurement method`
- Output refs: `decision_prototype/v1`
- Check IDs: `prototype_scope_check`

### `prototype_bound_experiment` (analysis)

Fix the time, tool, file, and command budget, declare the scratch directory or temporary worktree, name the executor or runtime and its capability limits, and pick the smallest artifact plus measurement method and stop conditions.

- Input refs: `experiment budget`, `scratch boundary`, `measurement method`
- Output refs: `decision_prototype/v1`
- Check IDs: `prototype_budget_isolation_check`, `prototype_smallest_artifact_check`

### `prototype_prepare_handoff` (production)

Write the exact commands, expected observations, workspace identity, and stop conditions as an executor-neutral handoff; production files are read-only inputs and no result is filled in before it is observed.

- Input refs: `experiment budget`, `scratch boundary`, `measurement method`
- Output refs: `prepared prototype handoff with exact commands and expected observations`
- Check IDs: `prototype_budget_isolation_check`, `prototype_smallest_artifact_check`
- If this step fails: unresolved; still stands: `decision_prototype/v1`; hand back: Return decision_prototype/v1 with draft commands, expected observations and the exact budget, runtime or write-boundary blocker; no command is authorized outside the declared scratch boundary.

### `prototype_record_observations` (validation)

Ingest only observed outputs and bounded evidence references, then derive interpretation, confidence, and unresolved questions in separate fields; an unavailable executor, timeout, or inconclusive run is recorded as that state, never as a result.

- Input refs: `experiment budget`, `measurement method`
- Output refs: `observation ledger separating observed outputs from interpretation and confidence`
- Check IDs: `prototype_execution_evidence_check`
- If this step fails: not_observed; still stands: `decision_prototype/v1`, `prepared prototype handoff with exact commands and expected observations`; hand back: Return the prepared prototype handoff with executor-unavailable or timeout status and any captured failure evidence; leave experiment results unobserved rather than filling the observation ledger with guesses.

### `prototype_close_receipt` (validation)

Decide keep or discard, observe cleanup before reporting `discarded`, and close with a compact decision receipt, handed to `ulw-plan` for planning, that needs no transcript replay and without any implementation handoff.

- Input refs: `decision question`, `experiment budget`, `scratch boundary`, `measurement method`
- Output refs: `decision receipt for planning with supported option, rejected option, residual risk, and evidence limits`, `decision_prototype/v1`
- Check IDs: `prototype_scope_check`, `prototype_budget_isolation_check`, `prototype_smallest_artifact_check`, `prototype_execution_evidence_check`, `prototype_cleanup_receipt_check`
- If this step fails: unresolved; still stands: `decision_prototype/v1`, `prepared prototype handoff with exact commands and expected observations`, `observation ledger separating observed outputs from interpretation and confidence`; hand back: Return the observation ledger and a decision receipt naming unresolved options, residual risk, evidence limits, keep/discard and cleanup status; block promotion until a separate accepted plan and handoff exist.
