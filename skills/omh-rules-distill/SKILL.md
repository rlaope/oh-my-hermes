---
name: "omh-rules-distill"
description: "[omh] Turn repeated lessons into written rules: extract repeated principles from skills, prompts, traces, reviews, and failures into reviewed rule candidates without auto-mutating guidance. Use when the user says: rules-distill, rules distill, distill rules, rule distillation, principle distill, skill principles, extract agent rules, turn traces into rules."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, knowledge]
    category: knowledge
    phase: rules-distillation
    role: memory-keeper
    quality_tier: rules-distillation-gated
    related_skills: [omh-workflow-learning, omh-wiki, omh-agent-instructions]
---

# Rules Distill

This is a Hermes-native `rules-distill` workflow skill.

## Why This Exists

`rules-distill` gives OMH a disciplined way to learn from large skill ecosystems like ECC without wholesale copying: extract principles, review them, then patch OMH only through explicit verified work.

## Do Not Use When

- The user wants a single workflow route regression; use `omh-workflow-learning`.
- The user wants durable factual project memory; use `omh-wiki` or memory curation.
- The user already approved a concrete code/doc change; use the implementation workflow.
- The ask is writing or keeping current the file an agent reads at startup -- AGENTS.md, CLAUDE.md, a Cursor rule; use `omh-agent-instructions`, which updates only its marked region.

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

- Every candidate in principle_candidate_set/v1 cites the repeated observations it rests on; a candidate resting on one observation stays needs-evidence in review_queue/v1.
- Every candidate is classed mechanical or judgement before it is worded. A mechanical candidate is a miss a machine can find from the text alone (a forbidden call, a disallowed import, a file in the wrong place), and its destination is a check (a linter rule, test, hook, or CI step); when the repository already has a check for it that never runs or no longer fails, the candidate is repairing that check, not adding another. Its approved_patch_handoff/v1 names the check and where it is wired, and sets as an acceptance criterion the run the implementer must observe: the check fails with the violation injected and passes once it is reverted. A mechanical candidate outside the chosen destination boundary is reported as a check proposal outside the boundary, never reworded as prose. Only judgement candidates, which need a reader (consistency across files, fit with the code around them), are worded as prose.
- duplication_conflict_report/v1 names the existing rule or check each candidate repeats or contradicts, or says none was found and where it looked.
- Nothing reached a destination without an approval recorded in review_queue/v1.

## Recovery Notes

- If a principle rests on one observation, retain its source reference in principle_candidate_set/v1, mark the rule tentative and needs-evidence in review_queue/v1, and hand back the candidate for repeated observations.
- If approval is missing, retain principle_candidate_set/v1 and duplication_conflict_report/v1, mark implementation not_observed, and hand back review_queue/v1 without producing approved_patch_handoff/v1.
- If skill_manage stages an approved change, retain the approved candidate and staged result, mark the skill update not_observed, and hand back the pending ID for the person's `/skills approve <id>`.

## Workflow Lane

- Current lane: **Automation and status** (`achievements`, `workspace-audit`, `production-audit`, `live-incident-response`, `automation-blueprint`, `github-event-ops`, `github-issue-intake`, `buzz`, `+40 more`) - schedules, status, health, and ops review.
- If intent belongs to another lane, hand back to `omh-routing` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use when Hermes should turn repeated workflow lessons, skill behavior, review comments, or failure traces into candidate rules that humans can review before docs or catalog changes.

    Strong routing signals: `rules-distill`, `rules distill`, `distill rules`, `rule distillation`, `principle distill`, `skill principles`, `extract agent rules`, `turn traces into rules`, `policy distill`, `guidance distill`, `규칙 증류`, `원칙 추출`, `스킬 원칙`, `프롬프트 규칙`

## Catalog Metadata

Category: `knowledge`
Phase: `rules-distillation`
Hermes role: `memory-keeper`
Quality tier: `rules-distillation-gated`
Reasoning demand: `light`

Quality bar:

- Collect repeated evidence before proposing a rule.
- Deduplicate against existing guidance and name conflicts or narrower scopes.
- Use imperative, testable wording and include non-goals for each candidate.
- Require review approval before any patch handoff or generated-skill update.
- On Hermes, read a curator run report (`logs/curator/<run>/REPORT.md` and `run.json` under the active profile's Hermes home) as a source like a review or a trace: it records which skills the curator consolidated, archived, or created in that run, and one report is one observation, never repeated evidence by itself.

Handoff policy:

Keep principle extraction and candidate review in Hermes. Editing AGENTS.md, catalog data, prompts, skills, or docs requires explicit approved implementation work and verification.

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

Safety rules:

- Do not silently mutate skills, prompts, AGENTS.md, docs, memory, or catalog data from a distillation result.
- Do not promote one-off preferences, weak anecdotes, or stale traces into global rules.
- Keep observed sources, inferred principles, candidate wording, review state, and implementation patches separate.
- On Hermes, when the destination is the user's own Hermes skills, an approved candidate lands through `skill_manage`: report it landed only from a result that succeeded without `staged: true`, with the matching skill audit ledger entry as its record while the ledger is on, and report a staged write as waiting in `/skills pending` for the person's own `/skills approve <id>` under their `skills.write_approval` setting. OMH-managed skills are generated from OMH's catalog and are never the destination; a lesson about one goes to `omh-workflow-learning`. An OMH-managed skill is one OMH installed, under a label OMH's catalog renders such as `omh-plan` or `ulw-work`; a companion skill the person or an agent created is theirs, whatever its name.

## Runtime Evidence

Preferred harness for this skill: `rules-distill`.

```sh
omh runtime record --skill rules-distill --harness rules-distill --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- Treat wrapper memory/context summaries as advisory local context, not proof of opaque Hermes memory reads or changes.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a real unresolved user decision or a useful briefing discussion remains, offer one specific, content-linked question. Completed work needs no question; omit unrelated non-action footers and generic offers to continue.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
