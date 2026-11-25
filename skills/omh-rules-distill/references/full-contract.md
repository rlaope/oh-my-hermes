# Rules Distill

Load this on-demand contract after the compact `rules-distill` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user wants a single workflow route regression; use `omh-workflow-learning`.
- The user wants durable factual project memory; use `omh-memory-new`, or `omh-memory-sync` to curate what Hermes already holds.
- The user already approved a concrete code/doc change; use the implementation workflow.
- The ask is writing or keeping current the file an agent reads at startup -- AGENTS.md, CLAUDE.md, a Cursor rule; use `omh-agent-instructions`, which updates only its marked region.
- The ask is shrinking a neural network's weights into a smaller student model; use `omh-model-compression`.

## Examples

Good example:

- Prompt: rules-distill 최근 실패 trace와 스킬들을 보고 OMH AGENTS에 넣을 만한 반복 원칙 후보만 뽑아줘.
- Expected behavior: Prepare principle_candidate_set/v1, duplication/conflict report, review queue, and approved patch handoff only after approval.
- Why: The request is meta-guidance learning and needs review before mutating rules.

Bad example:

- Prompt: rules-distill 한 번 본 실패를 바로 모든 스킬 규칙으로 써버려.
- Expected behavior: Keep it as a low-confidence candidate or regression case until repeated evidence and review approval exist.
- Why: Rule distillation should not turn one-off anecdotes into global behavior.

## Full Input, Output, and Artifact Expectations

Required inputs:

- source corpus: skills, prompts, traces, reviews, failures, or docs
- destination boundary: AGENTS, skills, prompt, docs, memory, check, or no-write review
- rule granularity and acceptance criteria
- reviewer or approval requirement

Expected outputs:

- rules_distillation_plan/v1
- principle_candidate_set/v1
- duplication_conflict_report/v1
- review_queue/v1
- approved_patch_handoff/v1 when approved
- not-evidence boundary

Artifact expectations:

- principle_candidate_set/v1 with source references, repeated pattern, mechanical or judgement class, candidate wording or check, scope, non-goals, and risk
- duplication_conflict_report/v1 with already-covered rules, conflicts, and stale guidance
- review_queue/v1 separating proposed, approved, rejected, deferred, and needs-evidence candidates
