---
name: code-review
description: Hermes Code Review workflow: bug-first review with evidence.
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, review]
    category: review
    phase: critique
    role: hybrid-review
    quality_tier: finding-evidence-gated
---

# Code Review

This is a Hermes-native `code-review` workflow skill.

## Use When

Use for review-shaped requests; findings come first and must cite concrete evidence.

    Strong routing signals: `code-review`, `$code-review`, `review`, `audit`, `find bugs`, `release gate`, `claim audit`, `evidence audit`, `README claim`, `what actually happened`, `릴리즈 전`, `실제 코드와 맞는가`, `실제로 뭐 했는지`, `검증된 결과`

## Catalog Metadata

Category: `review`
Phase: `critique`
Hermes role: `hybrid-review`
Quality tier: `finding-evidence-gated`

Quality bar:

- Lead with ranked findings grounded in file, diff, command, or artifact evidence.
- Separate review findings from fix implementation; fixes become executor work.
- Say clearly when no actionable issue is found and name remaining test gaps.

Handoff policy:

Hermes may frame and summarize review evidence; fixes or code mutations found during review should be delegated to the selected coding executor.

Required inputs:

- diff or files
- expected behavior
- test evidence

Expected outputs:

- ranked findings
- open questions
- test gaps

Artifact expectations:

- critic run record when review evidence is captured

Safety rules:

- Findings come before summaries.
- Cite concrete evidence for every finding.
- Say clearly when no issue is found.

## Harness Discipline

- Start from the representative harness registry in `oh-my-hermes` when the workflow needs coding, research, planning, goal execution, architecture, critique, QA, or documentation lanes.
- Prefer richer evidence and clearer stop conditions over adding more workflow names.
- Use specialist lanes only when they change the quality of the answer or verification.

## Runtime Evidence

Preferred harness for this skill: `critic`.

When local shell access or a bot wrapper is available, record metadata-only evidence:

```sh
omh runtime record --skill code-review --harness critic --status started
omh runtime delegate --run <run-id> --requested --not-observed --result not_observed
```

Record observed delegation results when Hermes or the wrapper exposes them. If delegation is unavailable, keep the result explicit as `not_available` or `not_observed`.

## Hermes Compatibility Contract

- Preserve the workflow intent, stop conditions, and verification discipline.
- Use Hermes-native tools, file operations, and subagent/delegation features when available.
- Do not require runtime tools, role prompts, or overlays that Hermes Agent does not expose.
- Respect `omh_target_topology/v1` when a wrapper reports it: bind state to the current target/thread, adapt only the parts of this workflow that benefit from multiple Hermes agents, and fall back to single-target behavior when `active_agent_count` is one.
- When target topology changes from one to many or many to one, give a concise setup-change comment or use the wrapper's apply action before treating the new topology as persistent.
- When wrapper metadata includes `memory_review_card/v1` or `handoff_context_pack/v1`, treat it as reviewed OMH-local or wrapper-supplied context only. Use conflict-free context summaries to shape plans and handoffs, but do not claim Hermes internal memory was read or changed.
- When a runtime-specific mechanism appears in imported instructions, translate it to a Hermes-native artifact:
  - goal tools -> `.omh/goals/` ledgers or explicit checklists,
  - question renderers -> one concise question in the current Hermes interface,
  - native subagents -> Hermes delegation when available, otherwise sequential lanes,
  - shell bridge commands -> optional bridge mode only.

## Execution Rules

1. Load supporting context with `skills_list` / `skill_view` when needed.
2. State the workflow target, constraints, validation evidence, and stop condition.
3. Keep progress evidence-backed.
4. Verify with the smallest relevant test or inspection before claiming completion.
5. If Hermes cannot provide a required runtime capability, say so and use the fallback above.
