---
name: web-research
description: [omh] Hermes Web Research workflow: source-backed current information gathering.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, research]
    category: research
    phase: current-evidence
    role: researcher
    quality_tier: source-gated
---

# Web Research

This is a Hermes-native `web-research` workflow skill.

## Why This Exists

`web-research` exists to make Hermes a careful source-backed research operator: it routes web/current-source requests to evidence gathering, keeps retrieval gaps visible, and prevents search plans from being reported as observed facts.

## Do Not Use When

- The user asks for a full plan-to-PR delivery cycle; use `ultraprocess` or a planning workflow after research instead.
- The request is purely local repo inspection with no external, current, citation, or source-comparison need.
- The user needs coding execution, review, CI, or merge evidence rather than research synthesis.

## Examples

Good example:

- Prompt: 웹서치해서 최신 자료와 출처를 정리해줘.
- Expected behavior: Run the Hermes web-research lane, ask for or state source boundaries and freshness, then summarize citations, confidence, and retrieval gaps.
- Why: The request explicitly asks for web search, current material, and sources without asking for implementation.

Bad example:

- Prompt: 웹리서치부터 계획, 구현, 리뷰, 문서, PR까지 한 사이클로 끝내줘.
- Expected behavior: Route to `ultraprocess` because the user asked for a bounded delivery cycle, not a research-only lane.
- Why: Research is only one stage of the requested delivery process.

## Completion Checklist

- The research question, source boundaries, recency assumptions, and confidence level are named.
- Observed sources, inference, synthesis, and unresolved retrieval gaps are separated.
- Follow-up planning or handoff uses the research summary without calling it execution evidence.

## Recovery Notes

- If sources cannot be accessed, state the retrieval gap and use only observed local context.
- If evidence is thin or one-sided, lower confidence and ask for a narrower source boundary.

## OMH Context Rail

- This skill is part of OMH's Hermes workflow layer, not a standalone executor.
- Product context: OMH is a Hermes-native workflow pack: it helps Hermes choose skills, shape work, prepare artifacts, show status, and hand off with observed evidence boundaries.
- Current lane: **Research and company ops** (`source-finder`, `web-research`, `best-practice-research`, `autoresearch-goal`, `research-brief`, `strategy-brief`, `feedback-triage`, `research-department`, `+5 more`) - source-backed research, customer signals, product operations, and briefing workflows.
- If the user intent belongs to another OMH lane, hand back to `oh-my-hermes` or name the adjacent workflow instead of force-fitting this skill.
- Cross-skill context: For every OMH skill: match intent to a lane; name adjacent workflows; generic tool can render or execute is not a dismissal.
- Generic-tool checkpoint: image->img-summary; frontend->frontend/visual-qa; paper->paper-learning; file->materials-package; search->web-research; audit->workspace-audit/production-audit; verify->verification-gate; code->ultraprocess.
- Coverage: Every generated workflow skill carries this rail.
- Normal users talk to Hermes; OMH CLI is backend, setup, verification, and wrapper infrastructure.
- Boundary: Prepared OMH routing, prompts, cards, handoffs, or artifacts are not observed execution, image generation, delivery, review, CI, merge-readiness, or merge evidence.

## Use When

Use when the user needs current web evidence, links, citations, source diversity, or source comparison before planning or handoff.

    Strong routing signals: `web-research`, `web research`, `web search`, `search the web`, `internet search`, `latest`, `fresh sources`, `current sources`, `current web evidence`, `source-backed research`, `source search`, `find sources`, `find citations`, `citation check`, `evidence scan`, `source diversity`, `retrieval gap`, `look up`, `lookup`, `investigate`, `research plan`, `웹서치`, `웹 서치`, `웹 검색`, `인터넷 검색`, `검색해줘`, `검색해서`, `최신 자료`, `최신 출처`, `자료 찾아`, `조사`, `근거`, `출처`, `고객 피드백`

## Catalog Metadata

Category: `research`
Phase: `current-evidence`
Hermes role: `researcher`
Quality tier: `source-gated`

Quality bar:

- Ask for the research question, source boundaries, freshness, jurisdiction, and version assumptions before retrieval.
- Use official or primary sources first when current or external facts matter, then add source diversity when the topic is contested.
- Separate direct evidence, citation links, retrieval dates, inference, confidence, and residual uncertainty.
- Name retrieval gaps when Hermes or the wrapper cannot access the web.
- Summarize research before any coding handoff; research is not implementation evidence.

Handoff policy:

Run as a Hermes-side research lane when web access is available; summarize evidence before any coding handoff and never treat research as implementation.

Required inputs:

- research question
- source boundaries
- freshness, jurisdiction, or version constraints

Expected outputs:

- source-backed synthesis
- links or citations
- source-quality notes
- confidence and residual uncertainty

Artifact expectations:

- research notes with source URLs, retrieval dates, and source-quality notes when the wrapper captures them

Safety rules:

- Prefer official or primary sources when they can answer the question.
- Check source diversity and conflicts before summarizing contested or unstable topics.
- Separate quoted evidence from inference.
- State retrieval limits, dates, and missing-source gaps for unstable facts.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `research`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill web-research --harness research --status started
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
