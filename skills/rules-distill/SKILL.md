---
name: rules-distill
description: [omh] Hermes Rules Distill workflow: extract repeated principles from skills, prompts, traces, reviews, and failures into reviewed rule candidates without auto-mutating guidance.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, knowledge]
    category: knowledge
    phase: rules-distillation
    role: memory-keeper
    quality_tier: rules-distillation-gated
---

# Rules Distill

This is a Hermes-native `rules-distill` workflow skill.

## Why This Exists

`rules-distill` gives OMH a disciplined way to learn from large skill ecosystems like ECC without wholesale copying: extract principles, review them, then patch OMH only through explicit verified work.

## Do Not Use When

- The user wants a single workflow route regression; use `workflow-learning`.
- The user wants durable factual project memory; use `wiki` or memory curation.
- The user already approved a concrete code/doc change; use the implementation workflow.

## Examples

Good example:

- Prompt: rules-distill 최근 실패 trace와 스킬들을 보고 OMH AGENTS에 넣을 만한 반복 원칙 후보만 뽑아줘.
- Expected behavior: Prepare principle_candidate_set/v1, duplication/conflict report, review queue, and approved patch handoff only after approval.
- Why: The request is meta-guidance learning and needs review before mutating rules.

Bad example:

- Prompt: rules-distill 한 번 본 실패를 바로 모든 스킬 규칙으로 써버려.
- Expected behavior: Keep it as a low-confidence candidate or regression case until repeated evidence and review approval exist.
- Why: Rule distillation should not turn one-off anecdotes into global behavior.

## Completion Checklist

- The durable fact, source evidence, retrieval hint, and staleness risk are recorded.
- Uncertain or conflicting knowledge is marked as review-needed rather than permanent truth.
- Separate coding or docs tasks are extracted instead of buried in notes.

## Recovery Notes

- If source evidence conflicts, route to memory or knowledge review before writing durable guidance.
- If the fact may be stale, record the staleness warning and next refresh action.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: it helps Hermes choose skills, shape work, prepare artifacts, show status, and hand off with observed evidence boundaries.
- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `automation-blueprint`, `github-event-ops`, `agent-board`, `gateway-intent-card`, `voice-operator`, `+11 more`) - scheduled ops, gateway cards, boards, tool readiness, status, health, and release/ops review.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: For every OMH skill: match intent to a lane; name adjacent workflows; generic tool can render or execute is not a dismissal.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/visual-qa; paper->paper-learning; file->materials-package; search->web-research; audit->workspace-audit/production-audit; verify->verification-gate; code->ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is backend, setup, verification, and wrapper infrastructure.
- Boundary: Prepared OMH routing, prompts, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when Hermes should turn repeated workflow lessons, skill behavior, review comments, or failure traces into candidate rules that humans can review before docs or catalog changes.

    Strong routing signals: `rules-distill`, `rules distill`, `distill rules`, `rule distillation`, `principle distill`, `skill principles`, `extract agent rules`, `turn traces into rules`, `policy distill`, `guidance distill`, `규칙 증류`, `원칙 추출`, `스킬 원칙`, `프롬프트 규칙`

## Catalog Metadata

Category: `knowledge`
Phase: `rules-distillation`
Hermes role: `memory-keeper`
Quality tier: `rules-distillation-gated`

Quality bar:

- Collect repeated evidence before proposing a rule.
- Deduplicate against existing guidance and name conflicts or narrower scopes.
- Use imperative, testable wording and include non-goals for each candidate.
- Require review approval before any patch handoff or generated-skill update.

Handoff policy:

Keep principle extraction and candidate review in Hermes. Editing AGENTS.md, catalog data, prompts, skills, or docs requires explicit approved implementation work and verification.

Required inputs:

- source corpus: skills, prompts, traces, reviews, failures, or docs
- destination boundary: AGENTS, skill catalog, prompt, docs, memory, or no-write review
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

- principle_candidate_set/v1 with source references, repeated pattern, candidate wording, scope, non-goals, and risk
- duplication_conflict_report/v1 with already-covered rules, conflicts, and stale guidance
- review_queue/v1 separating proposed, approved, rejected, deferred, and needs-evidence candidates

Safety rules:

- Do not silently mutate skills, prompts, AGENTS.md, docs, memory, or catalog data from a distillation result.
- Do not promote one-off preferences, weak anecdotes, or stale traces into global rules.
- Keep observed sources, inferred principles, candidate wording, review state, and implementation patches separate.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `rules-distill`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill rules-distill --harness rules-distill --status started
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record observed delegation results when Hermes or the wrapper exposes them. If delegation is unavailable, keep the result explicit as `not_available` or `not_observed`.

## Hermes Compatibility Contract

- Preserve the workflow intent, stop conditions, and verification discipline.
- Use Hermes-native tools, file operations, and subagent/delegation features when available.
- Do not require runtime tools, role prompts, or overlays that Hermes Agent does not expose.
- Respect `omh_target_topology/v1` when a wrapper reports it: bind state to the current target/thread, adapt only the parts of this workflow that benefit from multiple Hermes agents, and fall back to single-target behavior when `active_agent_count` is one.
- When target topology changes from one to many or many to one, give a concise setup-change comment or use the wrapper's apply action before treating the new topology as persistent.
- Treat wrapper-supplied memory/context summaries as advisory local context, not proof that opaque Hermes memory was read or changed.
- When a runtime-specific mechanism appears in imported instructions, translate it to a Hermes-native artifact:
  - goal tools -> `.omh/goals/` ledgers, `goal_completion_gate/v1`, `goal_status_card/v1`, `goal_continuation/v1`, or explicit checklists with named next actions,
  - question renderers -> one concise question in the current Hermes interface,
  - native subagents -> Hermes delegation when available, otherwise sequential lanes,
  - shell bridge commands -> optional bridge mode only.

## Execution Rules

1. Load supporting context with `skills_list` / `skill_view` when needed.
2. State the workflow target, constraints, validation evidence, and stop condition.
3. Keep progress evidence-backed.
4. Verify with the smallest relevant test or inspection before claiming completion.
5. If Hermes cannot provide a required runtime capability, say so and use the fallback above.
