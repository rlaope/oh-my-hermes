---
name: "omh-code-review"
description: "[omh] Pull request or changes to vet: bug-first review with evidence. Use when the user says: code-review, review, audit, find bugs, release gate, claim audit, evidence audit, README claim."
license: MIT
author: "oh-my-hermes maintainers"
metadata:
  hermes:
    tags: [workflow, oh-my-hermes, review]
    category: review
    phase: critique
    role: reviewer
    quality_tier: finding-evidence-gated
    related_skills: [sdlc-review, requesting-code-review]
---

# Code Review

This is a Hermes-native `code-review` workflow skill.

## Why This Exists

`code-review` exists to make review bug-first and evidence-grounded: findings must cite concrete files, diffs, commands, or artifacts before any summary or fix proposal.

## Do Not Use When

- The user asks to implement the fix rather than review existing code or claims.
- There is no diff, file set, claim, artifact, or expected behavior to review.
- The request is broad product critique, strategy, or planning rather than code or evidence review.
- A kanban review worker needs its card's transition decided: Hermes' bundled `sdlc-review` owns approve, request-changes, and escalate there, and this skill only supplies the findings that decision cites.
- The user wants their own uncommitted changes checked before a commit or push, with a security scan, quality gates, and fixes applied in place; load Hermes' bundled `requesting-code-review` skill for that pre-commit pass instead of this one.

## Examples

Good example:

- Prompt: $code-review review this PR for install/update UX regressions and missing tests.
- Expected behavior: Lead with ranked findings, cite concrete evidence, then list open questions and test gaps.
- Why: The task is explicitly review-shaped and has a behavioral risk surface.

Bad example:

- Prompt: $code-review add the missing setup flag and commit it.
- Expected behavior: Route implementation to a selected executor/runtime after review findings are established.
- Why: Review can identify the issue, but code mutation is a separate execution step.

## Completion Checklist

- Findings come first and are ranked by severity before summary or praise.
- Every finding cites file, diff, command output, artifact, or expected behavior evidence.
- Both axes appear in the report: correctness/risk findings, and a spec-axis verdict naming its Claim source or the `not_assessed` reason.
- No-issue reviews still name residual risk, missing tests, and independent review evidence if unavailable.
- The closing carries the checked-and-clean list and the could-not-assess list, each naming its surfaces.
- Fix implementation, architecture follow-up, and CI/merge claims stay separate from the review result.

## Recovery Notes

- If no diff, file set, PR, or artifact is available, inspect the requested target or ask one target question before reviewing.
- If tests fail or are missing, cite the exact command gap and do not approve the change as verified.
- If independent review evidence is unavailable, say so directly instead of implying a second reviewer passed it.
- To dispatch a reviewer rather than write the findings yourself, load `omh-code-review/references/review-dispatch.md`; it carries the base-SHA rule, the findings schema the return is checked against, and the implementer status contract.
- When findings arrive for work you own, load `omh-code-review/references/review-response.md` before changing anything.
- For maintainability judgement calls, load `omh-code-review/references/smell-baseline.md`; it names the twelve baseline smells with their fixes and the repo-standards-override rule.
- When one bug-first pass is not enough, load `omh-code-review/references/review-lenses.md` and run the five lenses separately; the verification-gap lens asks whether anything would go red if the changed behavior broke.

## Workflow Lane

- Current lane: **Coding handoff** (`idea-to-deploy`, `llm-app-dev`, `cto-loop`, `deploy-and-monitor`, `code-review`, `build-failure-triage`, `verification-gate`, `security-safety-review`, `+28 more`) - coding owners, handoffs, review, CI, and merge evidence.
- If intent belongs to another lane, hand back to `oh-my-hermes` or name the adjacent workflow.
- Shared product, routing, compatibility, and evidence rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`.

## When to Use

Use for review-shaped requests; findings come first and must cite concrete evidence.

    Strong routing signals: `code-review`, `$code-review`, `review`, `audit`, `find bugs`, `release gate`, `claim audit`, `evidence audit`, `README claim`, `what actually happened`, `code review`, `review gate`, `コードレビュー`, `バグを見つけて`, `実際に何をしたか`, `리뷰`, `코드 리뷰`, `리뷰까지`, `릴리즈 전`, `실제 코드와 맞는가`, `실제로 뭐 했는지`, `검증된 결과`, `代码评审`, `代码审查`, `找出缺陷`, `tinjau kode`, `review kode ini`, `bantu tinjau kode PR ini`, `tolong periksa diff ini untuk mencari bug`, `cek perubahan kode sebelum merge`, `ulas pull request ini`, `cari bug di perubahan ini`, `review PR ini dong`

## Catalog Metadata

Category: `review`
Phase: `critique`
Hermes role: `reviewer`
Quality tier: `finding-evidence-gated`
Reasoning demand: `standard`

Quality bar:

- Lead with ranked findings grounded in file, diff, command, or artifact evidence.
- Separate review findings from fix implementation; fixes become executor work.
- For Hermes-owned coding work, inspect `hermes_coding_harness/v1` and require review evidence before upgrading the reviewer lane.
- Say clearly when no actionable issue is found and name remaining test gaps.
- Report each finding with `priority` (`P0`-`P3`), `confidence`, `evidence`, `path`, and `line_range`, then close with one verdict of `ship` or `no_ship` plus its own `confidence`; a finding without a path and line range is an open question, not a finding.
- `REVIEW.md` in the reviewed repository defines what blocks: map its blocking definitions onto `P0`/`P1` and let a `no_ship` verdict follow from that file rather than from reviewer preference. When the repository has no such file, say which blocking definition was used instead.
- Review on two axes and report them side by side, never re-ranked against each other: the correctness/risk axis judges the code as it is, and the spec axis judges the diff against the dispatch's Claim and Requirements pointer. A clean diff that does not do what was asked is a spec-axis finding; when no Claim or spec pointer was supplied, report the spec axis as `not_assessed` with that reason instead of staying silent.
- Judge maintainability findings against the named baseline in `omh-code-review/references/smell-baseline.md`: a baseline smell is a judgement call to argue from evidence, never an automatic finding, and the reviewed repository's own standards override the baseline wherever they conflict.
- Close with two lists beside the verdict: what was checked and found clean, and what could not be assessed with the reason. An absent finding is evidence only when the closing says the surface was actually checked.
- Hermes handles two parts of a review itself; load `omh-code-review/references/native-review-contract.md` for both. When `delegate_task` is in your tool list or tool_search finds it, pass the findings schema as the reviewer task's `output_schema`. The host validates the return, but its `schema_valid` record reaches you only when the call returns its results in the same turn; a result that arrives later as a completion message carries none, so check that summary against the schema yourself and never read `completed` as validated. A return that fails the contract is `not_observed`, never a pass. Inside a kanban review worker, `no_ship` becomes the request-changes transition that `sdlc-review` makes.
- When the reviewed work ran in a Hermes session, cite `session_file_activity/v1` (`omh quality-evidence file-activity --hermes-session <id> --json`) to scope which workspace files its read_file, write_file, and patch calls touched, with the outcome Hermes recorded; it is file lineage, never file-content, diff, test, review, CI, or merge evidence.
- For native `omh_todo` checkpoints, load the todo-checklist closing recipe; `record` then `recall` this review declaration. Stored declarations are not proof.

Handoff policy:

Hermes may frame and summarize review evidence; fixes or code mutations found during review should be delegated to the selected coding executor.

Required inputs:

- diff or files
- expected behavior
- test evidence
- the dispatch Claim and Requirements pointer (issue, plan, or spec section) when intent is reviewable

Expected outputs:

- ranked findings per axis
- spec-axis verdict or a named not-assessed reason
- open questions
- test gaps
- checked-and-clean and could-not-assess lists

Artifact expectations:

- critic run record when review evidence is captured

Safety rules:

- Findings come before summaries.
- Cite concrete evidence for every finding.
- Say clearly when no issue is found.

## Runtime Evidence

Preferred harness for this skill: `critic`.

```sh
omh runtime record --skill code-review --harness critic --status started
```

Record observed delegation results; otherwise return `not_available` or `not_observed`.
Prepared OMH routing is not execution, review, CI, merge-readiness, or merge evidence.
- When wrapper metadata includes `memory_review_card/v1` or `handoff_context_pack/v1`, treat it as reviewed OMH-local or wrapper-supplied context only. Use conflict-free context summaries to shape plans and handoffs, but do not claim Hermes internal memory was read or changed.
Preserve workflow intent and stop conditions; verify before claiming completion.
Reply in the user's own words and the host's own voice: its SOUL.md persona owns reply language, tone, speech level, and sentence endings, progress updates included (where it sets no language, use the one the user wrote in), and OMH shapes structure and content only; OMH's record terms (surface, lane, wrapper, handoff, evidence boundary, not_observed) stay in records and tool calls, never in the sentence the user reads unless they ask about one; and when a stop condition or a decision the user owns ends the turn, offer the next action as a question rather than declaring what will not be done.

Use Hermes-native subagent/delegation features when available: native subagents -> Hermes delegation when available, otherwise sequential lanes.

Shared product, compatibility, topology, memory, harness, and execution rules: `skill_view(name='omh-routing', file_path='references/skill-common-rail.md')`. Load it when applicable; otherwise name an unavailable capability.
