---
name: research-department
description: [omh] Hermes Research Department workflow pack: prepare Scout, Analyst, and Briefer research operations with source inbox and briefing status boundaries.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: research-department
    role: researcher
    quality_tier: research-ops-gated
---

# Research Department

This is a Hermes-native `research-department` workflow skill.

## Why This Exists

`research-department` exists so Hermes users can start complex research-ops patterns without manually designing profiles, cron, knowledge storage, synthesis tooling, and delivery glue, while OMH keeps every runtime claim observed-only.

## Do Not Use When

- The user only needs a one-off current-source lookup; use `web-research`.
- The user only needs a one-off business synthesis; use `research-brief`.
- The request is pure scheduling with no source collection or synthesis; use `automation-blueprint`.
- The user asks for coding implementation; prepare a selected executor/runtime handoff after the research plan is accepted.

## Examples

Good example:

- Prompt: research-department 매일 경쟁사와 시장 뉴스를 수집해서 변화가 있으면 브리핑해줘.
- Expected behavior: Prepare research_department_plan/v1 with Scout/Analyst/Briefer lanes, source inbox buckets, briefing status, knowledge-store and synthesis-tool readiness, and observed-only evidence requirements.
- Why: The request is recurring, source-backed, and operational; a single research brief would miss the ongoing workflow/status boundary.

Bad example:

- Prompt: research-department prove the synthesis tool queried the knowledge base and posted the Slack brief.
- Expected behavior: Ask for observed synthesis-tool and gateway delivery evidence or mark those states as not_observed.
- Why: The workflow pack can prepare the operating pattern, but it cannot prove external tool execution or delivery.

## Use When

Use when Hermes should turn an ongoing or recurring research request into a prepared Scout -> Analyst -> Briefer workflow with source inbox, knowledge-store and synthesis-tool readiness, and briefing status without claiming research execution.

    Strong routing signals: `research-department`, `research department`, `research ops department`, `research operations department`, `scout analyst briefer`, `scout analyst brief`, `daily research department`, `competitor research department`, `market research department`, `paper review`, `weekly paper review`, `research paper review`, `paper research`, `notebooklm research`, `obsidian research vault`, `knowledge store`, `knowledge storage`, `synthesis tool`, `knowledge summarizer`, `research inbox`, `source inbox`, `briefing status`, `리서치 부서`, `리서치 조직`, `리서치 운영`, `수집 합성 브리핑`, `지식 저장소`, `요약 도구`, `경쟁사 리서치 부서`

## Catalog Metadata

Category: `research`
Phase: `research-department`
Hermes role: `researcher`
Quality tier: `research-ops-gated`

Quality bar:

- Name topic, source boundaries, cadence, delivery target, knowledge-store destination, and synthesis-tool readiness.
- Map Scout, Analyst, and Briefer lanes to concrete OMH skills and source inbox buckets.
- Expose collected, synthesized, briefed, conflict, and verification counts as status, not execution proof.
- List required evidence before claiming retrieval, synthesis, storage, delivery, or verification.

Handoff policy:

Keep the research operating model in Hermes. Map Scout to `web-research`/`autoresearch-goal`, Analyst to `research-brief`/`best-practice-research`, and Briefer to `report-package` or meeting/report workflows. Record retrieval, synthesis-tool output, knowledge-store writes, delivery, and verification only from observed evidence.

Required inputs:

- topic or watch area
- source boundaries
- cadence
- delivery target
- knowledge-store preference
- synthesis-tool preference

Expected outputs:

- research_department_plan/v1
- source_inbox/v1
- briefing_status/v1
- not-evidence boundary

Artifact expectations:

- research_department_plan/v1 under .omh/research-department/plans when a wrapper or CLI records it

Safety rules:

- Do not claim web retrieval, synthesis-tool query, knowledge-store write, cron creation, gateway delivery, or verification from a prepared plan.
- Keep raw findings, processed notes, briefs, conflicts, and verification needs in separate source inbox buckets.
- Treat vendor-specific tool names as optional aliases for synthesis-tool and knowledge-store readiness unless observed evidence exists.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `research-department`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill research-department --harness research-department --status started
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
