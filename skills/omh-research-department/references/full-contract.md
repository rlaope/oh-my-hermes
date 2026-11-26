# Research Department

Load this on-demand contract after the compact `research-department` body identifies the
workflow. The main body already holds `Why This Exists`, `First Steps`,
`Quality bar`, `Handoff policy`, `Safety rules`, `Completion Checklist`,
`Recovery Notes`, and the runtime rail; this file holds only the examples,
sibling routing boundaries, and expanded input/output/artifact lists.

## Do Not Use When

- The user only needs a one-off current-source lookup; use `omh-web-research` for one cited round, or `ulw-research` for a reference-implementation study with a depth budget.
- The user only needs a one-off business synthesis; use `omh-research-brief`.
- The request is pure scheduling with no source collection or synthesis; use `omh-automation-blueprint`.
- The user asks for coding implementation; prepare a selected executor/runtime handoff after the research plan is accepted.
- The request is one news watch over named companies, or a scheduled run of a watch that already exists, with no knowledge store, synthesis tool, or briefing lanes to set up, and Hermes' bundled `competitor-news-monitor` skill is available; load that skill.
- The user wants a one-off paper search by topic, author, category, or paper id rather than a recurring paper review, and Hermes' bundled `arxiv` skill is available; load that skill.

## Examples

Good example:

- Prompt: Set up a Scout, Analyst, and Briefer research flow for daily competitor and market changes.
- Expected behavior: Prepare research_department_plan/v1 with Scout/Analyst/Briefer lanes, source inbox buckets, briefing status, knowledge-store and synthesis-tool readiness, and observed-only evidence requirements.
- Why: The request is recurring, source-backed, and operational; a single research brief would miss the ongoing workflow/status boundary.

Bad example:

- Prompt: research-department prove the synthesis tool queried the knowledge base and posted the Slack brief.
- Expected behavior: Ask for observed synthesis-tool and gateway delivery evidence or mark those states as not_observed.
- Why: The workflow pack can prepare the operating pattern, but it cannot prove external tool execution or delivery.

## Full Input, Output, and Artifact Expectations

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
